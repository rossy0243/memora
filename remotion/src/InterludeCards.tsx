import React from "react";
import { AbsoluteFill, interpolate, spring, useCurrentFrame, useVideoConfig } from "remotion";
import { ACCENT_FONT, TITLE_FONT, ensureFonts } from "./fonts";

// Meme habillage que TitleCard (fond encre, accents dores) pour deux cartons
// additionnels, optionnels, geres cote Python (voir processing.remotion) :
// le mot des maries et le recap en chiffres. Un carton absent (message vide,
// stats nulles) n'est simplement jamais monte dans la TransitionSeries — voir
// MemoraFilm.tsx et timeline.ts.
const BACKGROUND = "radial-gradient(130% 130% at 50% 42%, #221d1f 0%, #171314 70%, #100d0e 100%)";
const GOLD = "#d8b46a";

function useCardFade(durationInFrames: number): number {
  const frame = useCurrentFrame();
  const enter = interpolate(frame, [0, 20], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  const exit = interpolate(frame, [durationInFrames - 14, durationInFrames], [1, 0], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  return Math.min(enter, exit);
}

export const MessageCard: React.FC<{
  message: string;
  signature: string;
  durationInFrames: number;
}> = ({ message, signature, durationInFrames }) => {
  ensureFonts();
  const frame = useCurrentFrame();
  const { fps, width, height } = useVideoConfig();
  const minSide = Math.min(width, height);
  const opacity = useCardFade(durationInFrames);
  const enter = spring({ frame, fps, config: { damping: 200 }, durationInFrames: 30 });
  const rise = interpolate(enter, [0, 1], [16, 0]);
  const ruleWidth = interpolate(enter, [0, 1], [0, minSide * 0.07]);

  return (
    <AbsoluteFill style={{ background: BACKGROUND, justifyContent: "center", alignItems: "center", opacity }}>
      <div
        style={{
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          gap: minSide * 0.03,
          padding: "0 12%",
          transform: `translateY(${rise}px)`,
        }}
      >
        <div
          style={{
            width: ruleWidth,
            height: Math.max(minSide * 0.0026, 1),
            background: `linear-gradient(90deg, rgba(216,180,106,0) 0%, ${GOLD} 50%, rgba(216,180,106,0) 100%)`,
          }}
        />
        <div
          style={{
            color: "#fdfaf6",
            fontFamily: `"${ACCENT_FONT}", Georgia, serif`,
            fontStyle: "italic",
            fontWeight: 500,
            fontSize: minSide * 0.05,
            lineHeight: 1.35,
            textAlign: "center",
            textShadow: "0 2px 14px rgba(0,0,0,0.35)",
          }}
        >
          « {message} »
        </div>
        {signature ? (
          <div
            style={{
              color: GOLD,
              fontFamily: `"${TITLE_FONT}", Georgia, serif`,
              fontSize: minSide * 0.028,
              letterSpacing: minSide * 0.005,
              textTransform: "uppercase",
            }}
          >
            {signature}
          </div>
        ) : null}
      </div>
    </AbsoluteFill>
  );
};

export const StatsCard: React.FC<{
  totalMemories: number;
  contributors: number;
  durationInFrames: number;
}> = ({ totalMemories, contributors, durationInFrames }) => {
  ensureFonts();
  const frame = useCurrentFrame();
  const { fps, width, height } = useVideoConfig();
  const minSide = Math.min(width, height);
  const opacity = useCardFade(durationInFrames);
  const enter = spring({ frame, fps, config: { damping: 200 }, durationInFrames: 30 });
  const scale = interpolate(enter, [0, 1], [0.92, 1]);
  const memoryWord = totalMemories > 1 ? "souvenirs partagés" : "souvenir partagé";

  return (
    <AbsoluteFill style={{ background: BACKGROUND, justifyContent: "center", alignItems: "center", opacity }}>
      <div
        style={{
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          gap: minSide * 0.014,
          transform: `scale(${scale})`,
        }}
      >
        <div
          style={{
            color: "#fdfaf6",
            fontFamily: `"${TITLE_FONT}", Georgia, serif`,
            fontWeight: 700,
            fontSize: minSide * 0.16,
            lineHeight: 1,
            textShadow: "0 2px 18px rgba(0,0,0,0.35)",
          }}
        >
          {totalMemories}
        </div>
        <div
          style={{
            color: GOLD,
            fontFamily: `"${ACCENT_FONT}", Georgia, serif`,
            fontSize: minSide * 0.038,
            letterSpacing: minSide * 0.007,
            textTransform: "uppercase",
          }}
        >
          {memoryWord}
        </div>
        {contributors > 1 ? (
          <div
            style={{
              color: "#c9b8ba",
              fontFamily: `"${ACCENT_FONT}", Georgia, serif`,
              fontSize: minSide * 0.028,
              marginTop: minSide * 0.008,
            }}
          >
            partagés par {contributors} invités
          </div>
        ) : null}
      </div>
    </AbsoluteFill>
  );
};
