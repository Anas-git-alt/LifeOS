import { memo } from "react";

function WidgetCard({ title, subtitle, status, actions, children, footer }) {
  return (
    <section className="glass-card widget-card">
      <header className="widget-card-head">
        <div>
          <h2>{title}</h2>
          {subtitle ? <p>{subtitle}</p> : null}
        </div>
        <div className="widget-card-head-right">
          {status ? <span className="widget-status">{status}</span> : null}
          {actions ? <div className="widget-actions">{actions}</div> : null}
        </div>
      </header>
      <div className="widget-card-body">{children}</div>
      {footer ? <footer className="widget-card-footer">{footer}</footer> : null}
    </section>
  );
}

export function WidgetSkeleton({ lines = 4 }) {
  return (
    <div className="widget-skeleton" aria-hidden="true">
      {Array.from({ length: lines }).map((_, index) => (
        <span key={index} className="widget-skeleton-line" />
      ))}
    </div>
  );
}

export function WidgetEmpty({ message, action }) {
  return (
    <div className="widget-empty-state">
      <p>{message}</p>
      {action || null}
    </div>
  );
}

export function WidgetError({ message, onRetry }) {
  return (
    <div className="widget-error-state">
      <p>{message || "Failed loading widget"}</p>
      <button className="btn btn-ghost" type="button" onClick={onRetry}>
        Retry
      </button>
    </div>
  );
}

export default memo(WidgetCard);
