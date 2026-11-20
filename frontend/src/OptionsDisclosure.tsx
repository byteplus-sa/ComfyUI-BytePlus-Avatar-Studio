import { useState, type ReactNode } from "react";
import { ChevronDown } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible";

export function OptionsDisclosure({
  title,
  children,
  invalid = false,
  defaultOpen = false,
}: {
  title: string;
  children: ReactNode;
  invalid?: boolean;
  defaultOpen?: boolean;
}) {
  const [open, setOpen] = useState(defaultOpen);
  const expanded = open || invalid;
  return (
    <Collapsible open={expanded} onOpenChange={setOpen} className="min-w-0">
      <CollapsibleTrigger asChild>
        <Button
          variant="ghost"
          size="sm"
          className="-ml-2.5 text-muted-foreground"
          aria-label={title}
        >
          {title}
          <ChevronDown
            className={`size-3.5 transition-transform ${expanded ? "rotate-180" : ""}`}
          />
        </Button>
      </CollapsibleTrigger>
      <CollapsibleContent forceMount hidden={!expanded} className="pt-4">
        {children}
      </CollapsibleContent>
    </Collapsible>
  );
}
