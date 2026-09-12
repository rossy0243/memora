import React from "react";
import {
  AbsoluteFill,
  Audio,
  interpolate,
  staticFile,
  useVideoConfig,
} from "remotion";
import { TransitionSeries, linearTiming } from "@remotion/transitions";
import { fade } from "@remotion/transitions/fade";
import { FilmProps } from "./types";
import { Clip } from "./Clip";
import { TitleCard } from "./TitleCard";
import { FilmGrain } from "./FilmGrain";
import { mainClips as resolveMainClips, usesColdOpen } from "./timeline";

function resolveSrc(src: string): string {
  return /^https?:\/\//.test(src) ? src : staticFile(src);
}

// Bandeaux "scope" (2.35:1) : reserves au heros, jamais au teaser (vertical,
// deja plein cadre) ni a l'integrale (format de conservation, pas de spectacle).
const CINEMATIC_ASPECT_RATIO = 2.35;

// Le film complet : carton d'ouverture -> plans en fondus enchaines -> carton de fin,
// avec une piste musicale par-dessus. Les fondus (fade) sont le choix le plus sobre ;
// le rythme vient de la duree des plans, calee sur le tempo cote Django.
export const MemoraFilm: React.FC<FilmProps> = (props) => {
  const {
    clips,
    audioSrc,
    audioFirstBeatOffset,
    title,
    subtitle,
    outroTitle,
    introDurationInFrames,
    outroDurationInFrames,
    transitionDurationInFrames,
    grade,
    pace,
    musicVolume,
    duckedMusicVolume,
    cinematicBars,
  } = props;
  const { fps, width, height } = useVideoConfig();

  // Ouverture a froid : les 2,5 premieres secondes montrent le premier plan
  // seul et muet, puis le titre se pose dessus en fondu — jamais un carton
  // plein qui demarre sec. On borne pour garder un minimum de texte lisible
  // meme sur un intro tres court. Ce plan ne reapparait pas juste apres dans
  // le montage (mainClips, partage avec timeline.ts pour que la duree annoncee
  // de la composition corresponde exactement a ce qui est rendu ici).
  const coldOpen = usesColdOpen(clips);
  const coldOpenFrames = coldOpen
    ? Math.min(Math.round(fps * 2.5), Math.max(introDurationInFrames - Math.round(fps * 1.5), 0))
    : 0;
  const coldOpenBackground = coldOpen
    ? { ...clips[0], keepAudio: false, durationInFrames: introDurationInFrames }
    : null;
  const mainClips = resolveMainClips(clips);

  // Bandeaux "scope" : hauteur calculee pour amener le cadre 16:9 a 2.35:1,
  // sans jamais recadrer le contenu — juste deux bandes posees par-dessus.
  const barHeight = cinematicBars
    ? Math.max((height - width / CINEMATIC_ASPECT_RATIO) / 2, 0)
    : 0;

  const transition = () => (
    <TransitionSeries.Transition
      presentation={fade()}
      timing={linearTiming({ durationInFrames: transitionDurationInFrames })}
    />
  );

  // Le lower-third (nom du moment) ne s'affiche que sur le PREMIER plan de chaque
  // moment : il marque l'entree dans un nouveau chapitre (Cérémonie, Soirée…)
  // sans repeter le libelle sur chaque photo.
  const seenLabels = new Set<string>();
  const clipLabels = mainClips.map((clip) => {
    const label = clip.label?.trim();
    if (!label || seenLabels.has(label)) return undefined;
    seenLabels.add(label);
    return label;
  });

  // Segments [debut, fin] (en frames) des plans qui gardent la voix des invites.
  // Dans une TransitionSeries, chaque transition CHEVAUCHE les deux sequences :
  // le plan i commence donc a (somme des durees precedentes) - (i+1) transitions.
  const voiceSegments: Array<[number, number]> = [];
  let clipStart = introDurationInFrames - transitionDurationInFrames;
  for (const clip of mainClips) {
    if (clip.keepAudio) {
      voiceSegments.push([clipStart, clipStart + clip.durationInFrames]);
    }
    clipStart += clip.durationInFrames - transitionDurationInFrames;
  }

  // Ducking : la musique descend a duckedMusicVolume pendant les passages avec
  // voix, avec une rampe douce d'un tiers de seconde de part et d'autre.
  const ramp = Math.max(Math.round(fps / 3), 1);
  const musicVolumeAt = (frame: number): number => {
    let volume = musicVolume;
    for (const [start, end] of voiceSegments) {
      const dip = interpolate(
        frame,
        [start - ramp, start, end, end + ramp],
        [musicVolume, duckedMusicVolume, duckedMusicVolume, musicVolume],
        { extrapolateLeft: "clamp", extrapolateRight: "clamp" }
      );
      volume = Math.min(volume, dip);
    }
    return volume;
  };

  return (
    <AbsoluteFill style={{ backgroundColor: "#0f0c0d" }}>
      <TransitionSeries>
        <TransitionSeries.Sequence durationInFrames={introDurationInFrames}>
          {coldOpenBackground ? (
            <AbsoluteFill>
              <Clip clip={coldOpenBackground} grade={grade} pace="gentle" />
              <TitleCard
                title={title}
                subtitle={subtitle}
                durationInFrames={introDurationInFrames}
                transparentBg
                revealDelay={coldOpenFrames}
              />
            </AbsoluteFill>
          ) : (
            <TitleCard
              title={title}
              subtitle={subtitle}
              durationInFrames={introDurationInFrames}
            />
          )}
        </TransitionSeries.Sequence>

        {mainClips.flatMap((clip, index) => [
          transition(),
          <TransitionSeries.Sequence
            key={`clip-${index}`}
            durationInFrames={clip.durationInFrames}
          >
            <Clip
              clip={clip}
              grade={grade}
              pace={pace}
              chapterLabel={clipLabels[index]}
              transitionDurationInFrames={transitionDurationInFrames}
            />
          </TransitionSeries.Sequence>,
        ])}

        {transition()}
        <TransitionSeries.Sequence durationInFrames={outroDurationInFrames}>
          <TitleCard
            title={outroTitle}
            subtitle={title}
            durationInFrames={outroDurationInFrames}
            showSeal
          />
        </TransitionSeries.Sequence>
      </TransitionSeries>

      {audioSrc ? (
        <Audio
          src={resolveSrc(audioSrc)}
          startFrom={Math.round(audioFirstBeatOffset * fps)}
          volume={musicVolumeAt}
        />
      ) : null}

      <FilmGrain />

      {cinematicBars && barHeight > 0 ? (
        <>
          <AbsoluteFill style={{ top: 0, height: barHeight, background: "#000" }} />
          <AbsoluteFill style={{ top: "auto", bottom: 0, height: barHeight, background: "#000" }} />
        </>
      ) : null}
    </AbsoluteFill>
  );
};
