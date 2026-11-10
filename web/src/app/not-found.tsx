import Link from "next/link";
import { connection } from "next/server";

export default async function NotFound() {
  // Rendered per request so its scripts carry the Content-Security-Policy nonce.
  await connection();
  return (
    <main className="mx-auto w-full max-w-[1180px] px-4 py-16 md:px-8">
      <p className="mono-label">Page not found</p>
      <h1 className="mt-3 font-serif text-5xl leading-none tracking-tight">Nothing is here</h1>
      <p className="mt-4 text-muted-foreground">
        <Link href="/" className="text-link inline-flex min-h-11 items-center">
          Go to the ProofMode check
        </Link>
      </p>
    </main>
  );
}
