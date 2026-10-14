"use client";
import { Button } from "@/components/ui/button";
export default function ErrorPage({ reset }: { reset: () => void }) {
  return (
    <div className="panel empty-state" role="alert">
      <h1>Something went wrong</h1>
      <p>We couldn’t display this page. Try loading it again.</p>
      <Button onClick={reset}>Try again</Button>
    </div>
  );
}
