import { forwardRef, useId } from 'react';
import { cn } from '@/shared/lib/utils/format';
import styles from './Field.module.css';

interface FieldProps {
  label?: string;
  hint?: string;
  error?: string;
  required?: boolean;
  htmlFor?: string;
  children: React.ReactNode;
  className?: string;
}

export function Field({ label, hint, error, required, htmlFor, children, className }: FieldProps) {
  return (
    <div className={cn(styles.field, className)}>
      {label && (
        <label className={styles.label} htmlFor={htmlFor}>
          {label}{required && <span className={styles.req}>*</span>}
        </label>
      )}
      {children}
      {error ? <p className={styles.error}>{error}</p> : hint ? <p className={styles.hint}>{hint}</p> : null}
    </div>
  );
}

export const Input = forwardRef<HTMLInputElement, React.InputHTMLAttributes<HTMLInputElement> & { invalid?: boolean }>(
  function Input({ invalid, className, type = 'text', ...props }, ref) {
    return <input ref={ref} type={type} className={cn(styles.control, invalid && styles.invalid, className)} {...props} />;
  },
);

export const Textarea = forwardRef<HTMLTextAreaElement, React.TextareaHTMLAttributes<HTMLTextAreaElement> & { invalid?: boolean }>(
  function Textarea({ invalid, className, ...props }, ref) {
    return <textarea ref={ref} className={cn(styles.control, styles.textarea, invalid && styles.invalid, className)} {...props} />;
  },
);

export const Select = forwardRef<HTMLSelectElement, React.SelectHTMLAttributes<HTMLSelectElement> & { invalid?: boolean }>(
  function Select({ invalid, className, children, ...props }, ref) {
    return (
      <select ref={ref} className={cn(styles.control, styles.select, invalid && styles.invalid, className)} {...props}>
        {children}
      </select>
    );
  },
);

interface SwitchProps {
  checked: boolean;
  onChange: (checked: boolean) => void;
  label?: string;
  disabled?: boolean;
}

export function Switch({ checked, onChange, label, disabled }: SwitchProps) {
  const id = useId();
  return (
    <div className={styles.switchRow}>
      <button
        id={id}
        type="button"
        role="switch"
        aria-checked={checked}
        disabled={disabled}
        className={cn(styles.switch, checked && styles.switchOn)}
        onClick={() => onChange(!checked)}
      >
        <span className={styles.knob} />
      </button>
      {label && <label htmlFor={id} className={styles.switchLabel} onClick={() => !disabled && onChange(!checked)}>{label}</label>}
    </div>
  );
}

interface CheckboxProps {
  checked: boolean;
  onChange: (checked: boolean) => void;
  label?: React.ReactNode;
  disabled?: boolean;
}

export function Checkbox({ checked, onChange, label, disabled }: CheckboxProps) {
  const id = useId();
  return (
    <div className={styles.checkRow}>
      <input
        id={id}
        type="checkbox"
        className={styles.checkbox}
        checked={checked}
        disabled={disabled}
        onChange={e => onChange(e.target.checked)}
      />
      {label && <label htmlFor={id} className={styles.checkLabel}>{label}</label>}
    </div>
  );
}
