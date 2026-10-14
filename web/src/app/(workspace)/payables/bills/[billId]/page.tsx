import { InvoiceReview } from "@/components/invoice-review";
export default async function Page({
  params,
}: {
  params: Promise<{ billId: string }>;
}) {
  return <InvoiceReview id={(await params).billId} />;
}
