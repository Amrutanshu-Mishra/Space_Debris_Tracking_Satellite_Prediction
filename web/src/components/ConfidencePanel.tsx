import "./ConfidencePanel.css";

/**
 * Where the project's central argument is made to the operator: risk_score and
 * confidence are two numbers, and neither is a probability of collision. Said
 * as prose in the interface's voice, not a boxed disclaimer.
 */

function bandWord(confidence: number): string {
  if (confidence >= 0.7) return "a high-confidence";
  if (confidence >= 0.4) return "a reduced-confidence";
  return "a low-confidence";
}

export function ConfidencePanel({
  confidence,
  confidenceNote,
  maxEpochAgeHours,
}: {
  confidence: number;
  confidenceNote: string;
  maxEpochAgeHours: number;
}): JSX.Element {
  const ageHours = Math.round(maxEpochAgeHours);

  return (
    <section className="confidence" aria-label="Confidence and what these numbers mean">
      <h2 className="confidence__heading">Confidence</h2>
      <p className="confidence__body">
        This is {bandWord(confidence)} screening result —{" "}
        <span className="confidence__num">{confidence.toFixed(2)}</span> on a 0–1 scale — and the
        driver is data age: the older of the two TLEs is{" "}
        <span className="confidence__num">{ageHours}</span> hours past its epoch. {confidenceNote}
      </p>
      <p className="confidence__body">
        Neither this nor the risk score is a probability of collision. Public TLEs carry no
        covariance, so there is nothing to compute a real probability from. The risk score only
        ranks this encounter&rsquo;s geometry against the others in the run; confidence says how far
        to trust that ranking as the elements age.
      </p>
    </section>
  );
}
