import { useState } from "react";
import { RotateCcw } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { OptionsDisclosure } from "./OptionsDisclosure";
import type { Job } from "./model";
import type { Studio } from "./useStudio";

export function Activity({
  studio,
  requestCancel,
  requestResolve,
}: {
  studio: Studio;
  requestCancel: (job: Job) => void;
  requestResolve: (job: Job) => void;
}) {
  const jobs = studio.project?.jobs;
  if (!jobs?.length) return null;
  const recent = [...jobs].reverse();
  const completed = recent.filter((job) => ["done", "dismissed"].includes(job.state));
  const visible = recent.filter((job) => !["done", "dismissed"].includes(job.state));
  const renderJob = (job: Job) => (
    <ActivityRow
      key={job.id}
      job={job}
      studio={studio}
      requestCancel={requestCancel}
      requestResolve={requestResolve}
    />
  );
  return (
    <section className="activity" aria-labelledby="activity-title">
      <div className="activity-heading">
        <h2 id="activity-title">Activity</h2>
      </div>
      {visible.map(renderJob)}
      {completed.length > 0 && (
        <div className="mt-3">
          <OptionsDisclosure title={`Completed activity (${completed.length})`}>
            {completed.map(renderJob)}
          </OptionsDisclosure>
        </div>
      )}
    </section>
  );
}

function ActivityRow({
  job,
  studio,
  requestCancel,
  requestResolve,
}: {
  job: Job;
  studio: Studio;
  requestCancel: (job: Job) => void;
  requestResolve: (job: Job) => void;
}) {
  const [taskId, setTaskId] = useState("");
  const value = job.task_id || taskId;
  return (
    <div className="activity-row">
      <span className={`status-dot status-${job.state}`} />
      <div className="activity-description">
        <strong>
          {
            {
              image: "Character portrait",
              audio: "Narration",
              video: "Avatar video",
            }[job.kind]
          }
          <span className="tag">{job.state}</span>
        </strong>
        <p>{job.message}</p>
        {job.task_id && <code>{job.task_id}</code>}
      </div>
      {job.kind !== "video" &&
        job.state === "unknown" &&
        "runner" in job &&
        job.runner === "preparation" && (
          <Button
            variant="outline"
            size="sm"
            disabled={studio.working}
            onClick={() => requestResolve(job)}
          >
            Resolve preparation
          </Button>
        )}
      {job.kind === "video" && ["unknown", "failed"].includes(job.state) && (
        <div className="recovery-control">
          <Input
            aria-label={`Original OmniHuman task ID for ${job.id}`}
            placeholder="Original task ID"
            value={value}
            readOnly={Boolean(job.task_id)}
            maxLength={200}
            onChange={(event) => setTaskId(event.target.value)}
          />
          <Button
            variant="outline"
            size="sm"
            disabled={studio.working || !value.trim()}
            onClick={() => void studio.recover(job, value)}
          >
            <RotateCcw size={14} /> Collect task
          </Button>
        </div>
      )}
      {job.kind === "video" &&
        job.task_id &&
        ["running", "queued", "unknown"].includes(job.state) && (
          <Button
            variant="ghost"
            size="sm"
            disabled={studio.working}
            onClick={() => requestCancel(job)}
          >
            Request cancellation
          </Button>
        )}
    </div>
  );
}
