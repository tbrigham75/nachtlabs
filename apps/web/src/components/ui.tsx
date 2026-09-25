"use client";
import { useEffect, useId, useRef, useState } from "react";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { ApiError } from "@nachtlabs/api-client";

export interface Field { name: string; label: string; type?: string; required?: boolean; min?: number; max?: number; help?: string; options?: { value: string; label: string }[]; }
export function Form({ fields, initial = {}, submit, label = "Save", children }: {
  fields: Field[]; initial?: Record<string, string>; submit: (values: Record<string, string>) => Promise<void>; label?: string; children?: React.ReactNode;
}) {
  const prefix = useId();
  const shape: Record<string, z.ZodTypeAny> = {};
  fields.forEach(field => {
    let rule = z.string().max(field.max ?? 8000);
    if (field.required) rule = rule.min(field.min ?? 1, "This field is required");
    if (field.type === "email") rule = rule.email("Enter a valid email address");
    shape[field.name] = rule;
  });
  const { register, handleSubmit, formState, setError, resetField } = useForm<Record<string, string>>({ defaultValues: initial, resolver: zodResolver(z.object(shape)) });
  return <form className="form" onSubmit={handleSubmit(async values => {
    try { await submit(values); fields.filter(field => field.type === "password").forEach(field => resetField(field.name, {defaultValue:""})); } catch (error) { setError("root", {message: error instanceof Error ? error.message : "Unable to save"}); }
  })}>
    {fields.map(field => <div className="field" key={field.name}><label htmlFor={`${prefix}-${field.name}`}>{field.label}{field.required && <span aria-hidden="true"> *</span>}</label>
      {field.options ? <select id={`${prefix}-${field.name}`} {...register(field.name)} aria-describedby={`${prefix}-${field.name}-help`}>{field.options.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}</select> : field.type === "textarea" ? <textarea id={`${prefix}-${field.name}`} rows={4} {...register(field.name)} aria-describedby={`${prefix}-${field.name}-help`} /> : <input id={`${prefix}-${field.name}`} type={field.type ?? "text"} step={field.type === "number" ? "any" : undefined} autoComplete={field.type === "password" ? "new-password" : "off"} {...register(field.name)} aria-describedby={`${prefix}-${field.name}-help`} />}
      <small id={`${prefix}-${field.name}-help`}>{formState.errors[field.name]?.message ?? field.help}</small>
    </div>)}
    {children}{formState.errors.root && <p className="error" role="alert">{formState.errors.root.message}</p>}
    <button className="primary" disabled={formState.isSubmitting} type="submit">{formState.isSubmitting ? "Saving…" : label}</button>
  </form>;
}
export function ErrorNotice({ error }: { error: unknown }) {
  if (!error) return null;
  return <div role="alert" className="notice error">{error instanceof Error ? error.message : "Request unavailable"}{error instanceof ApiError && error.requestId && <small>Request {error.requestId}</small>}</div>;
}
export function Loading() { return <div className="loading" role="status"><span className="skeleton" />Loading…</div>; }
export function Heading({ title, note, children }: { title: string; note?: string; children?: React.ReactNode }) {
  return <header className="page-heading"><div><p className="eyebrow">NachtLabs / Control plane</p><h1>{title}</h1>{note && <p>{note}</p>}</div>{children}</header>;
}
export function Badge({ children, good = false }: { children: React.ReactNode; good?: boolean }) { return <span className={`badge ${good ? "good" : ""}`}>{children}</span>; }
export function Empty({ title, children }: { title: string; children?: React.ReactNode }) { return <div className="empty"><h2>{title}</h2>{children}</div>; }
export function Action({ children, action, danger = false }: {children: React.ReactNode; action: () => Promise<unknown>; danger?: boolean}) {
  const [error, setError] = useState<unknown>(); const [busy, setBusy] = useState(false);
  return <span className="action"><button className={danger ? "danger" : ""} disabled={busy} onClick={async () => { setBusy(true); setError(undefined); try { await action(); } catch (e) { setError(e); } finally { setBusy(false); } }}>{busy ? "Working…" : children}</button><ErrorNotice error={error} /></span>;
}
export function Dialog({ title, close, children }: {title: string; close: () => void; children: React.ReactNode}) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => { const node = ref.current; node?.showModal(); return () => node?.close(); }, []);
  return <dialog ref={ref} onCancel={close} aria-label={title}><div className="dialog-heading"><h2>{title}</h2><button onClick={close} aria-label="Close dialog">×</button></div>{children}</dialog>;
}
export function SecretNotice({ value, dismiss }: {value: string; dismiss: () => void}) {
  return <section className="notice warning"><h2>Save this value now</h2><p>This value is displayed only during this creation step. Store it securely.</p><pre>{value}</pre><button onClick={dismiss}>I have saved it — hide</button></section>;
}
