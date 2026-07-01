import type { RosterUser, TeamOption } from "@/components/PlanBuilder";
import { apiFetch } from "@/lib/api";

interface Page<T> {
  items: T[];
  next_cursor: string | null;
}

/**
 * Load the full team roster. The roster endpoint is keyset-paginated (default
 * page is small), but the planner needs everyone so a team can be expanded into
 * all of its members, so we page through until the cursor runs out.
 */
export async function fetchAllRoster(): Promise<RosterUser[]> {
  const all: RosterUser[] = [];
  let cursor: string | null = null;
  do {
    const qs = `?limit=100${cursor ? `&cursor=${encodeURIComponent(cursor)}` : ""}`;
    const page: Page<RosterUser> = await apiFetch<Page<RosterUser>>(
      `/v1/users/roster${qs}`,
    );
    all.push(...page.items);
    cursor = page.next_cursor;
  } while (cursor);
  return all;
}

/** Load active teams (paged) for the planner's team chips. */
export async function fetchAllTeams(): Promise<TeamOption[]> {
  const all: TeamOption[] = [];
  let cursor: string | null = null;
  do {
    const qs = `?limit=100${cursor ? `&cursor=${encodeURIComponent(cursor)}` : ""}`;
    const page: Page<TeamOption> = await apiFetch<Page<TeamOption>>(
      `/v1/teams${qs}`,
    );
    all.push(...page.items);
    cursor = page.next_cursor;
  } while (cursor);
  return all;
}
