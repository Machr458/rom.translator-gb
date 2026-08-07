import { useEffect, useRef } from "react";

const KIND_COLOR = {
  sys: "text-neutral-500",
  cmd: "text-[#9BBC0F] terminal-glow",
  info: "text-neutral-400",
  ok: "text-[#8BAC0F]",
  err: "text-[#C7305C]",
};

export default function Terminal({ logs }) {
  const boxRef = useRef(null);
  useEffect(() => {
    if (boxRef.current) boxRef.current.scrollTop = boxRef.current.scrollHeight;
  }, [logs]);

  return (
    <div
      ref={boxRef}
      className="bg-black h-64 sm:h-72 overflow-y-auto p-4 font-mono text-xs leading-relaxed"
      data-testid="terminal-log"
    >
      {logs.map((l, i) => (
        <div key={i} className={KIND_COLOR[l.kind] || "text-neutral-400"}>
          {l.line}
        </div>
      ))}
      <div className="text-[#8BAC0F] inline-block">
        <span className="terminal-glow">$</span>
        <span className="cursor-blink terminal-glow">_</span>
      </div>
    </div>
  );
}
