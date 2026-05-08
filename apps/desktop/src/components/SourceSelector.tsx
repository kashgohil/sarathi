export type AudioSource = "mic" | "system" | "both";

export function SourceSelector({
  value,
  onChange,
  disabled,
}: {
  value: AudioSource;
  onChange: (v: AudioSource) => void;
  disabled?: boolean;
}) {
  return (
    <select
      value={value}
      onChange={(e) => onChange(e.target.value as AudioSource)}
      disabled={disabled}
      className="bg-night-rise border border-page-rule rounded-full text-[11.5px] tracking-tight px-3 py-1.5 text-page-dim hover:text-page disabled:opacity-50 transition"
      title="Audio source"
    >
      <option value="mic">Microphone</option>
      <option value="system">System audio</option>
      <option value="both">Mic + system</option>
    </select>
  );
}
