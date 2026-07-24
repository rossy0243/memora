import React from "react";
import {
  AbsoluteFill,
  Img,
  OffthreadVideo,
  interpolate,
  staticFile,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";
import { FilmClip, FilmProps } from "./types";
import { gradeFilter, vignette } from "./grade";
import { ACCENT_FONT, ensureFonts } from "./fonts";

// Resout un chemin : URL absolue telle quelle, sinon fichier statique du bundle.
function resolveSrc(src: string): string {
  return /^https?:\/\//.test(src) ? src : staticFile(src);
}

// Amplitude du Ken Burns selon le rythme du format.
const KEN_BURNS: Record<FilmProps["pace"], [number, number]> = {
  punchy: [1.08, 1.2],
  balanced: [1.06, 1.14],
  gentle: [1.04, 1.1],
};

// Lower-third : nom du moment, sur le premier plan du chapitre. Entree en fondu +
// glissement, maintien, sortie en fondu — jamais affiche tout le long du plan.
const ChapterLabel: React.FC<{ label: string; durationInFrames: number }> = ({
  label,
  durationInFrames,
}) => {
  ensureFonts();
  const frame = useCurrentFrame();
  const { width, height } = useVideoConfig();
  const minSide = Math.min(width, height);

  const holdEnd = Math.min(78, durationInFrames - 12);
  const opacity = interpolate(
    frame,
    [6, 20, Math.max(holdEnd, 22), Math.max(holdEnd + 12, 34)],
    [0, 1, 1, 0],
    { extrapolateLeft: "clamp", extrapolateRight: "clamp" }
  );
  const slide = interpolate(frame, [6, 22], [minSide * 0.02, 0], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });

  const gold = "#e2c079";
  return (
    <AbsoluteFill
      style={{
        justifyContent: "flex-end",
        alignItems: "center",
        paddingBottom: height * 0.12,
        opacity,
      }}
    >
      {/* Scrim degrade pour la lisibilite du texte sur photo claire. */}
      <AbsoluteFill
        style={{
          background:
            "linear-gradient(0deg, rgba(0,0,0,0.42) 0%, rgba(0,0,0,0) 26%)",
        }}
      />
      <div
        style={{
          transform: `translateY(${slide}px)`,
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          gap: minSide * 0.018,
        }}
      >
        <div
          style={{
            width: minSide * 0.07,
            height: Math.max(minSide * 0.0026, 1),
            background: `linear-gradient(90deg, rgba(226,192,121,0) 0%, ${gold} 50%, rgba(226,192,121,0) 100%)`,
          }}
        />
        <div
          style={{
            color: "#fdfaf6",
            fontFamily: `"${ACCENT_FONT}", Georgia, serif`,
            fontSize: minSide * 0.044,
            fontWeight: 600,
            letterSpacing: minSide * 0.012,
            textTransform: "uppercase",
            textShadow: "0 2px 14px rgba(0,0,0,0.5)",
            whiteSpace: "nowrap",
          }}
        >
          {label}
        </div>
      </div>
    </AbsoluteFill>
  );
};

export const Clip: React.FC<{
  clip: FilmClip;
  grade: FilmProps["grade"];
  pace: FilmProps["pace"];
  chapterLabel?: string;
}> = ({ clip, grade, pace, chapterLabel }) => {
  const frame = useCurrentFrame();

  // Ken Burns : zoom lent et continu, centre. Donne du mouvement a une photo fixe
  // et une respiration cinema a une video. L'amplitude suit le rythme du format.
  const [from, to] = KEN_BURNS[pace] ?? KEN_BURNS.balanced;
  const scale = interpolate(frame, [0, clip.durationInFrames], [from, to], {
    extrapolateRight: "clamp",
  });

  const media =
    clip.kind === "video" ? (
      <OffthreadVideo src={resolveSrc(clip.src)} muted />
    ) : (
      <Img src={resolveSrc(clip.src)} />
    );

  return (
    <AbsoluteFill style={{ backgroundColor: "#0f0c0d", overflow: "hidden" }}>
      {/* Fond floute plein cadre : evite les bandes noires sur un media dont le
          ratio ne colle pas au format (vertical dans du 16:9 et inversement). */}
      <AbsoluteFill
        style={{
          transform: "scale(1.2)",
          filter: "blur(40px) brightness(0.5)",
        }}
      >
        <AbsoluteFill
          style={{
            display: "flex",
            justifyContent: "center",
            alignItems: "center",
          }}
        >
          <div style={{ width: "100%", height: "100%" }}>
            {clip.kind === "video" ? (
              <OffthreadVideo
                src={resolveSrc(clip.src)}
                muted
                style={{ width: "100%", height: "100%", objectFit: "cover" }}
              />
            ) : (
              <Img
                src={resolveSrc(clip.src)}
                style={{ width: "100%", height: "100%", objectFit: "cover" }}
              />
            )}
          </div>
        </AbsoluteFill>
      </AbsoluteFill>

      {/* Media net, contenu entier, avec Ken Burns et grade. */}
      <AbsoluteFill
        style={{
          display: "flex",
          justifyContent: "center",
          alignItems: "center",
          transform: `scale(${scale})`,
          filter: gradeFilter(grade),
        }}
      >
        {React.cloneElement(media, {
          style: { width: "100%", height: "100%", objectFit: "contain" },
        })}
      </AbsoluteFill>

      {/* Vignette douce par-dessus. */}
      <AbsoluteFill style={{ background: vignette }} />

      {/* Lower-third du moment, uniquement sur le premier plan du chapitre. */}
      {chapterLabel ? (
        <ChapterLabel label={chapterLabel} durationInFrames={clip.durationInFrames} />
      ) : null}
    </AbsoluteFill>
  );
};
