interface Props {
  regime: "bull" | "bear" | "sideways";
}

export default function RegimeBadge({ regime }: Props) {
  const config = {
    bull: { label: "Bull", className: "bg-green-500/10 text-green-500 border-green-500/30" },
    bear: { label: "Bear", className: "bg-red-500/10 text-red-500 border-red-500/30" },
    sideways: { label: "Sideways", className: "bg-yellow-500/10 text-yellow-500 border-yellow-500/30" },
  };

  const { label, className } = config[regime];

  return (
    <span
      className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium border capitalize ${className}`}
    >
      {label}
    </span>
  );
}
