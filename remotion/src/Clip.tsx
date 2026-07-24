import React from "react";
import {
  AbsoluteFill,
  Img,
  OffthreadVideo,
  interpolate,
  staticFile,
  useCurrentFrame,
} from "remotion";
import { FilmClip, FilmProps } from "./types";
import { gradeFilter, vignette } from "./grade";

// Resout un chemin : URL absolue telle quelle, sinon fichier statique du bundle.
function resolveSrc(src: string): string {
  return /^https?:\/\//.test(src) ? src : staticFile(src);
}

export const Clip: React.FC<{
  clip: FilmClip;
  grade: FilmProps["grade"];
}> = ({ clip, grade }) => {
  const frame = useCurrentFrame();

  // Ken Burns : zoom lent et continu, centre. Donne du mouvement a une photo fixe
  // et une respiration cinema a une video.
  const scale = interpolate(frame, [0, clip.durationInFrames], [1.06, 1.14], {
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
    </AbsoluteFill>
  );
};
