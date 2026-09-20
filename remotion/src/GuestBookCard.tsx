import React from "react";
import { NameCard } from "./NameCard";
import { TitleCard } from "./TitleCard";
import { GuestBookCardProps } from "./types";

// Carton du livre d'or rendu en IMAGE FIXE (renderStill), pas en video : le
// pipeline hybride (voir processing/guestbook_montage.py) en fait des segments
// ffmpeg avec fondu. Une video de carton coutait une minute de Chrome logiciel ;
// une image, une ou deux secondes. Le carton est rendu a un instant ou toutes
// ses animations d'entree sont terminees et ou la sortie n'a pas commence.
export const GuestBookCard: React.FC<GuestBookCardProps> = ({
  kind,
  title,
  subtitle,
  name,
  durationInFrames,
}) => {
  if (kind === "name") {
    return <NameCard name={name} durationInFrames={durationInFrames} />;
  }
  return (
    <TitleCard title={title} subtitle={subtitle} durationInFrames={durationInFrames} />
  );
};
