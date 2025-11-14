declare namespace Deno {
  namespace env {
    function get(key: string): string | undefined;
  }

  function serve(
    handler: (request: Request) => Response | Promise<Response>,
  ): void;
}

declare module "https://esm.sh/v135/@supabase/supabase-js@2.43.1?target=deno" {
  type NewsUrlRow = { id: number; url: string | null };

  interface SupabaseQueryBuilder
    extends PromiseLike<{ data: NewsUrlRow[] | null; error: Error | null }> {
    select(columns: string): SupabaseQueryBuilder;
    order(column: string, options: { ascending: boolean }): SupabaseQueryBuilder;
    limit(count: number): SupabaseQueryBuilder;
    is(column: string, value: unknown): SupabaseQueryBuilder;
    not(column: string, operator: "is" | string, value: unknown): SupabaseQueryBuilder;
  }

  interface SupabaseClient {
    from(table: string): SupabaseQueryBuilder;
  }

  export function createClient(...args: unknown[]): SupabaseClient;
}
