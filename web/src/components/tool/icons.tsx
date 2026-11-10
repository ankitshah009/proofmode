interface IconProps {
  className?: string;
}

const BASE = {
  viewBox: "0 0 16 16",
  fill: "none",
  stroke: "currentColor",
  strokeWidth: 2,
  strokeLinecap: "round",
  strokeLinejoin: "round",
  "aria-hidden": true,
} as const;

export function CheckIcon({ className = "size-3.5" }: IconProps) {
  return (
    <svg {...BASE} className={`flex-none ${className}`}>
      <path d="M2.5 8.5l3.5 3.5 7.5-8" />
    </svg>
  );
}

export function CrossIcon({ className = "size-3.5" }: IconProps) {
  return (
    <svg {...BASE} className={`flex-none ${className}`}>
      <path d="M3.5 3.5l9 9M12.5 3.5l-9 9" />
    </svg>
  );
}

export function QuestionIcon({ className = "size-3.5" }: IconProps) {
  return (
    <svg {...BASE} className={`flex-none ${className}`}>
      <path d="M5.5 6a2.5 2.5 0 1 1 3.6 2.2c-.7.4-1.1.9-1.1 1.8M8 13v.2" />
    </svg>
  );
}

export function UploadIcon({ className = "size-5" }: IconProps) {
  return (
    <svg {...BASE} className={`flex-none ${className}`}>
      <path d="M8 12.5v-9M4 7l4-4 4 4" />
    </svg>
  );
}
