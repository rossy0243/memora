import React from "react";
import {
  AbsoluteFill,
  Easing,
  Img,
  OffthreadVideo,
  interpolate,
  staticFile,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";
import { FilmProps, HighlightClip } from "./types";
import { gradeFilter } from "./grade";

function resolveSrc(src: string): string {
  return /^https?:\/\//.test(src) ? src : staticFile(src);
}

// Chaque vignette entre en decale (delayFrames) : un assemblage qui se
// construit sous l'oeil, pas un plaquage brut des trois photos d'un coup.
const Tile: React.FC<{
  clip: HighlightClip;
  grade: FilmProps["grade"];
  delayFrames: number;
  durationInFrames: number;
}> = ({ clip, grade, delayFrames, durationInFrames }) => {
  const frame = useCurrentFrame();
  const localFrame = Math.max(frame - delayFrames, 0);
  const scale = interpolate(localFrame, [0, durationInFrames], [1.04, 1.12], {
    extrapolateRight: "clamp",
    easing: Easing.out(Easing.ease),
  });
  const opacity = interpolate(localFrame, [0, 14], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });

  return (
    <div style={{ position: "relative", width: "100%", height: "100%", overflow: "hidden", opacity }}>
      <div style={{ position: "absolute", inset: 0, transform: `scale(${scale})`, filter: gradeFilter(grade) }}>
        {clip.kind === "video" ? (
          <OffthreadVideo
            src={resolveSrc(clip.src)}
            muted
            style={{ width: "100%", height: "100%", objectFit: "cover" }}
          />
        ) : (
          <Img src={resolveSrc(clip.src)} style={{ width: "100%", height: "100%", objectFit: "cover" }} />
        )}
      </div>
    </div>
  );
};

// Mini-collage des meilleurs moments festifs (voir processing.remotion,
// _select_highlight_uploads) : un dernier clin d'oeil avant la sortie, comme
// le recap qui cloture beaucoup de films de mariage. 2 ou 3 photos seulement
// (jamais de video en gros plan ici : la juxtaposition sied aux photos, pas a
// des videos qui jouent simultanement).
export const HighlightCollage: React.FC<{
  clips: HighlightClip[];
  grade: FilmProps["grade"];
  durationInFrames: number;
}> = ({ clips, grade, durationInFrames }) => {
  const { fps } = useVideoConfig();
  const stagger = Math.round(fps * 0.15);
  const gap = 6;

  return (
    <AbsoluteFill style={{ backgroundColor: "#100d0e" }}>
      <div
        style={{
          position: "absolute",
          inset: gap,
          display: "grid",
          gridTemplateColumns: clips.length >= 3 ? "1.4fr 1fr" : "1fr 1fr",
          gridTemplateRows: clips.length >= 3 ? "1fr 1fr" : "1fr",
          gap,
        }}
      >
        {clips.length >= 3 ? (
          <>
            <div style={{ gridRow: "1 / span 2", minHeight: 0 }}>
              <Tile clip={clips[0]} grade={grade} delayFrames={0} durationInFrames={durationInFrames} />
            </div>
            <div style={{ minHeight: 0 }}>
              <Tile clip={clips[1]} grade={grade} delayFrames={stagger} durationInFrames={durationInFrames} />
            </div>
            <div style={{ minHeight: 0 }}>
              <Tile clip={clips[2]} grade={grade} delayFrames={stagger * 2} durationInFrames={durationInFrames} />
            </div>
          </>
        ) : (
          <>
            <div style={{ minHeight: 0 }}>
              <Tile clip={clips[0]} grade={grade} delayFrames={0} durationInFrames={durationInFrames} />
            </div>
            <div style={{ minHeight: 0 }}>
              <Tile clip={clips[1]} grade={grade} delayFrames={stagger} durationInFrames={durationInFrames} />
            </div>
          </>
        )}
      </div>
    </AbsoluteFill>
  );
};
