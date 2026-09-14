/**
 * Pista em perspectiva — atmosfera no terço inferior, sem competir com o formulário.
 * Motion leve no espírito Animista (FreeBSD License).
 */
export default function Runway() {
  return (
    <div className="runway-stage" aria-hidden="true">
      <div className="runway-haze" />
      <div className="runway">
        <div className="runway-deck">
          <span className="runway-mark left" />
          <span className="runway-mark right" />
          <span className="runway-centerline" />
          <span className="runway-lights left">
            {Array.from({ length: 8 }, (_, i) => (
              <i key={`l${i}`} style={{ "--i": i }} />
            ))}
          </span>
          <span className="runway-lights right">
            {Array.from({ length: 8 }, (_, i) => (
              <i key={`r${i}`} style={{ "--i": i }} />
            ))}
          </span>
        </div>
      </div>
    </div>
  );
}
