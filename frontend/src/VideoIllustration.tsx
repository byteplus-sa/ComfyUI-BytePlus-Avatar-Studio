import { AudioLines, Sparkles, UserRound } from "lucide-react";

const WAVEFORM = [8, 14, 24, 16, 34, 42, 26, 18, 32, 46, 30, 20, 12, 22, 10];

export function VideoIllustration() {
  return (
    <div className="video-illustration" aria-hidden="true">
      <div className="illustration-orbit" />
      <div className="illustration-portrait">
        <div className="illustration-portrait-top">
          <span />
          <span />
        </div>
        <div className="illustration-person">
          <UserRound strokeWidth={1} />
        </div>
        <div className="illustration-portrait-line" />
      </div>
      <div className="illustration-audio">
        <AudioLines className="size-4" strokeWidth={1.5} />
        <div className="illustration-waveform">
          {WAVEFORM.map((height, index) => (
            <span key={index} style={{ height }} />
          ))}
        </div>
      </div>
      <div className="illustration-spark">
        <Sparkles strokeWidth={1.4} />
      </div>
    </div>
  );
}
