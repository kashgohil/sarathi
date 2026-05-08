//! Sample-aligned mic + system audio mixer.
//!
//! Both inputs are 16 kHz mono int16 PCM. The mixer holds two ring buffers,
//! ticks every `TICK_MS`, takes `min(len(mic), len(sys))` samples from each,
//! sums them with int16 clipping, and forwards a single `audio` command to
//! the sidecar.
//!
//! Drift handling
//! --------------
//! Mic and system have independent clocks. Over time their buffers diverge.
//! On every tick we trim the longer buffer to within `MAX_DRIFT_MS` of the
//! shorter one — drops audio rather than letting one source slip an entire
//! utterance behind. This is crude (no resampling) but adequate for VAD-
//! gated transcription where small phase errors don't matter.
//!
//! Single-source fallback
//! ----------------------
//! If one source goes silent for `SINGLE_SOURCE_GRACE_MS`, the mixer flushes
//! whatever the other source has alone. Useful when the user picks "Mic +
//! system" but Screen Recording permission is denied — they still get mic
//! transcripts instead of nothing.

use base64::Engine;
use parking_lot::Mutex;
use serde_json::Value;
use std::sync::Arc;
use std::time::{Duration, Instant};
use tokio::sync::oneshot;

const SAMPLE_RATE: usize = 16_000;
const TICK_MS: u64 = 250;
const TICK_SAMPLES: usize = SAMPLE_RATE * TICK_MS as usize / 1000;
const MAX_DRIFT_MS: u64 = 1500;
const MAX_DRIFT_SAMPLES: usize = SAMPLE_RATE * MAX_DRIFT_MS as usize / 1000;
const SINGLE_SOURCE_GRACE_MS: u64 = 1500;

/// Bound on per-source ring buffer length. ~5s of audio. Anything beyond
/// this signals the consumer is way behind and we drop the oldest data.
const RING_CAP_SAMPLES: usize = SAMPLE_RATE * 5;

#[derive(Default)]
struct Channel {
    buf: Vec<i16>,
    last_push: Option<Instant>,
    dropped_samples: usize,
}

impl Channel {
    fn push(&mut self, mut samples: Vec<i16>) {
        self.last_push = Some(Instant::now());
        let new_len = self.buf.len() + samples.len();
        if new_len > RING_CAP_SAMPLES {
            let drop = new_len - RING_CAP_SAMPLES;
            if drop >= self.buf.len() {
                let extra = drop - self.buf.len();
                self.buf.clear();
                if extra > 0 {
                    samples.drain(..extra.min(samples.len()));
                }
                self.dropped_samples += drop;
            } else {
                self.buf.drain(..drop);
                self.dropped_samples += drop;
            }
        }
        self.buf.extend(samples);
    }

    fn drain_n(&mut self, n: usize) -> Vec<i16> {
        let take = n.min(self.buf.len());
        self.buf.drain(..take).collect()
    }

    fn trim_to(&mut self, max_len: usize) {
        if self.buf.len() > max_len {
            let drop = self.buf.len() - max_len;
            self.buf.drain(..drop);
            self.dropped_samples += drop;
        }
    }
}

#[derive(Default)]
struct State {
    mic: Channel,
    sys: Channel,
}

pub struct Mixer {
    state: Arc<Mutex<State>>,
    stop: Mutex<Option<oneshot::Sender<()>>>,
}

impl Mixer {
    pub fn spawn(sidecar_send: impl Fn(Value) + Send + Sync + 'static) -> Arc<Self> {
        let state = Arc::new(Mutex::new(State::default()));
        let (stop_tx, stop_rx) = oneshot::channel();
        let me = Arc::new(Self {
            state: state.clone(),
            stop: Mutex::new(Some(stop_tx)),
        });

        let send = Arc::new(sidecar_send);
        tokio::spawn(tick_loop(state, send, stop_rx));
        me
    }

    pub fn push_mic(&self, samples: Vec<i16>) {
        self.state.lock().mic.push(samples);
    }

    pub fn push_system(&self, samples: Vec<i16>) {
        self.state.lock().sys.push(samples);
    }

    pub fn stop(&self) {
        if let Some(tx) = self.stop.lock().take() {
            let _ = tx.send(());
        }
    }
}

async fn tick_loop(
    state: Arc<Mutex<State>>,
    sidecar_send: Arc<dyn Fn(Value) + Send + Sync>,
    mut stop: oneshot::Receiver<()>,
) {
    let mut ticker = tokio::time::interval(Duration::from_millis(TICK_MS));
    ticker.set_missed_tick_behavior(tokio::time::MissedTickBehavior::Delay);

    let engine = base64::engine::general_purpose::STANDARD;

    loop {
        tokio::select! {
            _ = &mut stop => break,
            _ = ticker.tick() => {
                let mixed = {
                    let mut s = state.lock();
                    drift_correct(&mut s);
                    mix_one_tick(&mut s)
                };
                if let Some(samples) = mixed {
                    let bytes = i16_to_le_bytes(&samples);
                    sidecar_send(serde_json::json!({
                        "type": "audio",
                        "pcm_b64": engine.encode(bytes),
                    }));
                }
            }
        }
    }
}

fn drift_correct(s: &mut State) {
    // If one side has been silent past the grace window and the other has
    // backlog, trim the active side so we don't accumulate forever.
    let mic_len = s.mic.buf.len();
    let sys_len = s.sys.buf.len();
    if mic_len > sys_len + MAX_DRIFT_SAMPLES {
        s.mic.trim_to(sys_len + MAX_DRIFT_SAMPLES);
    } else if sys_len > mic_len + MAX_DRIFT_SAMPLES {
        s.sys.trim_to(mic_len + MAX_DRIFT_SAMPLES);
    }
}

fn mix_one_tick(s: &mut State) -> Option<Vec<i16>> {
    let now = Instant::now();
    let grace = Duration::from_millis(SINGLE_SOURCE_GRACE_MS);

    let mic_alive = s.mic.last_push.map_or(false, |t| now.duration_since(t) < grace);
    let sys_alive = s.sys.last_push.map_or(false, |t| now.duration_since(t) < grace);

    match (mic_alive, sys_alive) {
        (true, true) => {
            let n = TICK_SAMPLES.min(s.mic.buf.len()).min(s.sys.buf.len());
            if n == 0 {
                return None;
            }
            let m = s.mic.drain_n(n);
            let y = s.sys.drain_n(n);
            Some(sum_with_clip(&m, &y))
        }
        (true, false) => {
            let n = TICK_SAMPLES.min(s.mic.buf.len());
            if n == 0 {
                return None;
            }
            Some(s.mic.drain_n(n))
        }
        (false, true) => {
            let n = TICK_SAMPLES.min(s.sys.buf.len());
            if n == 0 {
                return None;
            }
            Some(s.sys.drain_n(n))
        }
        (false, false) => None,
    }
}

fn sum_with_clip(a: &[i16], b: &[i16]) -> Vec<i16> {
    a.iter()
        .zip(b.iter())
        .map(|(x, y)| {
            let s = (*x as i32) + (*y as i32);
            s.clamp(i16::MIN as i32, i16::MAX as i32) as i16
        })
        .collect()
}

fn i16_to_le_bytes(samples: &[i16]) -> Vec<u8> {
    let mut out = Vec::with_capacity(samples.len() * 2);
    for s in samples {
        out.extend_from_slice(&s.to_le_bytes());
    }
    out
}

/// Decode base64-encoded little-endian int16 PCM into `Vec<i16>`. Used by
/// the Tauri command that the frontend mic worklet posts to.
pub fn decode_pcm_b64(b64: &str) -> Result<Vec<i16>, String> {
    let bytes = base64::engine::general_purpose::STANDARD
        .decode(b64)
        .map_err(|e| format!("bad base64: {}", e))?;
    if bytes.len() % 2 != 0 {
        return Err("odd-length pcm".into());
    }
    Ok(bytes
        .chunks_exact(2)
        .map(|c| i16::from_le_bytes([c[0], c[1]]))
        .collect())
}

/// Decode raw little-endian int16 PCM bytes (no base64) — used by the
/// system-audio path which streams PCM straight from the helper's stdout.
pub fn decode_pcm_le(bytes: &[u8]) -> Vec<i16> {
    bytes
        .chunks_exact(2)
        .map(|c| i16::from_le_bytes([c[0], c[1]]))
        .collect()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn sum_with_clip_clamps_high() {
        let a = vec![20_000_i16, -20_000];
        let b = vec![20_000_i16, -20_000];
        let out = sum_with_clip(&a, &b);
        assert_eq!(out, vec![i16::MAX, i16::MIN]);
    }

    #[test]
    fn channel_drops_oldest_when_capped() {
        let mut c = Channel::default();
        c.push(vec![1; RING_CAP_SAMPLES]);
        c.push(vec![2; 1000]);
        assert_eq!(c.buf.len(), RING_CAP_SAMPLES);
        assert_eq!(c.dropped_samples, 1000);
        assert_eq!(*c.buf.last().unwrap(), 2);
    }

    #[test]
    fn pcm_roundtrip() {
        let s = vec![0_i16, 1, -1, 30_000, -30_000];
        let bytes = i16_to_le_bytes(&s);
        let back = decode_pcm_le(&bytes);
        assert_eq!(s, back);
    }
}
