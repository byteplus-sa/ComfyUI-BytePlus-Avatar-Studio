import { useRef, useState } from "react";
import { ArrowUpRight, FileText, Plus, Search, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import byteplusLogo from "./byteplus-logo.svg?inline";
import type { Studio } from "./useStudio";

interface SidebarProps {
  studio: Studio;
  onSelect: (id: string) => void;
  onCreate: () => void;
  onHome: () => void;
}

export function Brand() {
  return (
    <span className="brand">
      <img src={byteplusLogo} alt="BytePlus" width="130" height="30" />
      <span className="brand-sub">Avatar Studio</span>
    </span>
  );
}

export function ProjectList({
  studio,
  onSelect,
  onCreate,
}: Omit<SidebarProps, "onHome">) {
  const [query, setQuery] = useState("");
  const search = useRef<HTMLInputElement>(null);
  const filter = query.trim().toLocaleLowerCase();
  const projects = studio.projects.filter((project) =>
    (project.title || "Untitled avatar").toLocaleLowerCase().includes(filter),
  );
  return (
    <>
      <Button
        variant="outline"
        className="new-project w-full justify-start"
        disabled={studio.working || studio.booting}
        onClick={onCreate}
      >
        <Plus /> New project
      </Button>
      <div className="project-heading">Projects</div>
      {(studio.projects.length >= 6 || query !== "") && (
        <div className="project-search">
          <Search
            className="pointer-events-none absolute left-3 top-1/2 size-3.5 -translate-y-1/2 text-muted-foreground"
            aria-hidden="true"
          />
          <Input
            ref={search}
            type="search"
            aria-label="Search projects"
            placeholder="Search projects"
            maxLength={120}
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            className="h-10 bg-transparent pl-9 pr-9 text-base md:h-9 md:text-xs [&::-webkit-search-cancel-button]:appearance-none"
          />
          {query && (
            <Button
              variant="ghost"
              size="icon-sm"
              className="absolute right-0.5 top-1/2 -translate-y-1/2"
              aria-label="Clear project search"
              onClick={() => {
                setQuery("");
                search.current?.focus();
              }}
            >
              <X className="size-3.5" />
            </Button>
          )}
        </div>
      )}
      <nav className="project-list" aria-label="Projects">
        {projects.map((project) => (
          <Button
            variant="ghost"
            key={project.id}
            title={project.title || "Untitled avatar"}
            className="project-link w-full justify-start overflow-hidden px-3 text-xs font-normal text-muted-foreground aria-[current=page]:bg-accent aria-[current=page]:text-foreground"
            disabled={studio.working}
            aria-current={
              project.id === studio.project?.id ? "page" : undefined
            }
            onClick={() => onSelect(project.id)}
          >
            <FileText className="size-3.5 text-muted-foreground" />
            <span className="truncate">
              {project.title || "Untitled avatar"}
            </span>
          </Button>
        ))}
        {!projects.length && (
          <p role="status" className="px-3 py-2 text-xs text-muted-foreground">
            {studio.projects.length
              ? "No matching projects."
              : "No projects yet."}
          </p>
        )}
      </nav>
    </>
  );
}

export function Sidebar({ studio, onSelect, onCreate, onHome }: SidebarProps) {
  return (
    <aside className="sidebar" aria-label="Workspace navigation">
      <button
        className="brand-button"
        aria-label="BytePlus Avatar Studio home"
        onClick={onHome}
      >
        <Brand />
      </button>
      <ProjectList studio={studio} onSelect={onSelect} onCreate={onCreate} />
      <div className="sidebar-bottom">
        <Button
          variant="ghost"
          asChild
          className="w-full justify-between text-xs text-muted-foreground"
        >
          <a
            href="https://byteplus-sa.github.io/ComfyUI-BytePlus-ModelArk/nodes/omnihuman/"
            target="_blank"
            rel="noreferrer"
          >
            Documentation <ArrowUpRight className="size-3.5" />
          </a>
        </Button>
        <div className="connection">
          <span className={`dot ${studio.setup?.ready ? "online" : ""}`} />
          {studio.setup?.test_mode
            ? "Offline preview"
            : studio.setup?.ready
              ? "ComfyUI connected"
              : "Setup required"}
        </div>
      </div>
    </aside>
  );
}
