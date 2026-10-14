import { redirect } from "next/navigation";
import { authenticated } from "@/lib/auth";
import { Shell } from "@/components/shell";
export default async function WorkspaceLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  if (!(await authenticated())) redirect("/login");
  return <Shell>{children}</Shell>;
}

// Authentication must always be evaluated at request time, including builds
// where deployment secrets have not yet been configured.
export const dynamic = "force-dynamic";
