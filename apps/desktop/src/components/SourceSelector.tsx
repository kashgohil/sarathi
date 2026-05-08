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
      className="bg-neutral-900 border border-neutral-700 rounded text-xs px-2 py-1 disabled:opacity-50"
      title="Audio source"
    >
      <option value="mic">Microphone</option>
      <option value="system">System audio</option>
      <option value="both">Mic + system</option>
    </select>
  );
}
