import { sellerIntentDefinitions } from "../../lib/seller-intent";

export default function SellerIntentStatus({ status, compact = false }: { status?: string | null; compact?: boolean }) {
  const value = status && sellerIntentDefinitions[status] ? status : "UNKNOWN";
  const shortValue = value.replace("SIGNAL_IDENTIFIED", "SIGNAL").replace("DIRECTLY_EXPRESSED", "DIRECT").replace("ENGAGED_IN_DISCUSSION", "ENGAGED").replace("FORMAL_PROCESS", "FORMAL").replace("NOT_INTERESTED", "NOT INTERESTED");
  return <span className="column-definition seller-intent-status"><span>{compact ? shortValue : value}</span><span className="definition-banner">{sellerIntentDefinitions[value]}</span></span>;
}
