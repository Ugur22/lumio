import { Description, Field, Input, Label, Textarea } from "@headlessui/react";
import type { ComponentPropsWithRef, ComponentPropsWithoutRef, ReactNode } from "react";
import { cx, fieldBase } from "./styles";

type Own = {
  invalid?: boolean;
  // On a card (bg-surface) instead of the page (bg-bg).
  surface?: boolean;
  className?: string;
};

// `ref` is accepted so a form can move focus to the field that needs fixing.
export type TextInputProps = Omit<ComponentPropsWithRef<"input">, "className"> & Own;
export type TextAreaProps = Omit<ComponentPropsWithoutRef<"textarea">, "className"> & Own;

// The bare control, for inputs that carry an aria-label instead of a visible label.
export function TextInput({ surface, className, ...rest }: TextInputProps) {
  return <Input {...rest} className={cx(fieldBase, surface ? "bg-surface" : "bg-bg", className)} />;
}

export function TextArea({ surface, className, ...rest }: TextAreaProps) {
  return <Textarea {...rest} className={cx(fieldBase, "resize-y", surface ? "bg-surface" : "bg-bg", className)} />;
}

const labelClass = "text-[13px] font-medium";

interface TextFieldProps extends TextInputProps {
  label: ReactNode;
  description?: ReactNode;
  // Replaces the description and marks the input invalid.
  error?: ReactNode;
  // Extra content between the input and its description.
  children?: ReactNode;
  fieldClassName?: string;
}

// Headless Field wires the label and description to the input, so no ids are written by hand.
export function TextField({ label, description, error, children, fieldClassName, ...input }: TextFieldProps) {
  const note = error || description;
  return (
    <Field className={cx("flex flex-col gap-1.5", fieldClassName)}>
      <Label className={labelClass}>{label}</Label>
      <TextInput {...input} invalid={!!error || input.invalid} />
      {children}
      {note && <Description className={cx("text-[12px]", error ? "text-warn-bar" : "text-muted")}>{note}</Description>}
    </Field>
  );
}

interface TextAreaFieldProps extends TextAreaProps {
  label: ReactNode;
  description?: ReactNode;
  // Right-aligned under the textarea, such as a character counter.
  footer?: ReactNode;
  // Between the description and the textarea.
  children?: ReactNode;
  fieldClassName?: string;
}

export function TextAreaField({ label, description, footer, children, fieldClassName, ...textarea }: TextAreaFieldProps) {
  return (
    <Field className={cx("flex flex-col gap-2", fieldClassName)}>
      <Label className={labelClass}>{label}</Label>
      {description && <Description className="text-[12px] text-muted">{description}</Description>}
      {children}
      <TextArea {...textarea} />
      {footer && <div className="self-end">{footer}</div>}
    </Field>
  );
}
