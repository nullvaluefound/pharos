import { Link } from "react-router-dom";

export function NotFoundPage() {
  return (
    <div className="flex h-full items-center justify-center">
      <div className="text-center">
        <div className="text-6xl font-bold text-ink-300">404</div>
        <p className="mt-2 text-ink-500">This page doesn't exist.</p>
        <Link to="/stream" className="btn-primary mt-4 inline-flex">
          Back to stream
        </Link>
      </div>
    </div>
  );
}
