import { type LucideIcon } from "lucide-react";

interface Props {
  icon?: LucideIcon;
  title: string;
  hint?: string;
  action?: React.ReactNode;
}

export function Empty({ icon: Icon, title, hint, action }: Props) {
  return (
    <div className="flex flex-col items-center justify-center rounded-xl border border-dashed border-ink-200 bg-white px-6 py-16 text-center">
      {Icon && (
        <div className="mb-4 grid h-12 w-12 place-items-center rounded-full bg-ink-100 text-ink-400">
          <Icon className="h-6 w-6" />
        </div>
      )}
      <h3 className="text-base font-semibold text-ink-900">{title}</h3>
      {hint && <p className="mt-1 max-w-sm text-sm text-ink-500">{hint}</p>}
      {action && <div className="mt-4">{action}</div>}
    </div>
  );
}
