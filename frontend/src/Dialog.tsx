import { useRef, type ReactNode } from "react";
import { X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import {
  Dialog as DialogRoot,
  DialogContent,
  DialogTitle,
} from "@/components/ui/dialog";

interface DialogProps {
  title: string;
  children: ReactNode;
  onClose: () => void;
  busy?: boolean;
  sheet?: boolean;
  className?: string;
}

export function Dialog({
  title,
  children,
  onClose,
  busy = false,
  sheet = false,
  className,
}: DialogProps) {
  const previousFocus = useRef(document.activeElement);
  return (
    <DialogRoot
      open
      onOpenChange={(open) => {
        if (!open && !busy) onClose();
      }}
    >
      <DialogContent
        className={cn(
          sheet
            ? "project-sheet left-0 top-0 flex h-dvh w-[min(85vw,320px)] max-w-none translate-x-0 translate-y-0 flex-col rounded-none border-y-0 border-l-0"
            : "modal",
          className,
        )}
        aria-describedby={undefined}
        aria-busy={busy}
        onEscapeKeyDown={(event) => {
          if (busy) event.preventDefault();
        }}
        onInteractOutside={(event) => event.preventDefault()}
        onCloseAutoFocus={(event) => {
          event.preventDefault();
          const element = previousFocus.current;
          if (element instanceof HTMLElement && element.isConnected)
            element.focus();
        }}
      >
        <div className="mb-6 flex items-center justify-between gap-4">
          <DialogTitle className="text-lg font-semibold tracking-tight">
            {title}
          </DialogTitle>
          <Button
            variant="ghost"
            size="icon-sm"
            aria-label="Close dialog"
            disabled={busy}
            onClick={onClose}
          >
            <X />
          </Button>
        </div>
        {children}
      </DialogContent>
    </DialogRoot>
  );
}
