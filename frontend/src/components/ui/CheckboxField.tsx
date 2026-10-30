import { Checkbox, Description, Field, Label } from "@headlessui/react";
import type { ReactNode } from "react";
import { CheckIcon } from "../icons";
import { cx, focusRing } from "./styles";

interface Props {
  checked: boolean;
  onChange: (checked: boolean) => void;
  label: ReactNode;
  description?: ReactNode;
  disabled?: boolean;
  // A single-line label with the box centred on it, for use inside a row of controls.
  compact?: boolean;
  className?: string;
}

export function CheckboxField({ checked, onChange, label, description, disabled, compact, className }: Props) {
  return (
    <Field disabled={disabled} className={cx("flex", compact ? "items-center gap-1.5" : "items-start gap-2.5", className)}>
      <Checkbox
        checked={checked}
        onChange={onChange}
        className={cx(
          "group grid size-4 flex-none place-items-center rounded border border-border bg-bg data-[checked]:border-accent data-[checked]:bg-accent data-[disabled]:opacity-50",
          !compact && "mt-0.5",
          focusRing,
        )}
      >
        <CheckIcon width={12} height={12} aria-hidden="true" className="text-on-accent opacity-0 group-data-[checked]:opacity-100" />
      </Checkbox>
      <div className="flex flex-col">
        <Label className={cx("text-[13px]", !compact && "font-medium")}>{label}</Label>
        {description && <Description className="text-[12px] text-muted">{description}</Description>}
      </div>
    </Field>
  );
}
