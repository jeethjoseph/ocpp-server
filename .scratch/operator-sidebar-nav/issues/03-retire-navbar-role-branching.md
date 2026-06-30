# Retire role-branching from the old Navbar

Status: done
Type: AFK
Resolution: Implemented 2026-06-23. Removed adminNavigation/franchiseeNavigation arrays and the role-branch from Navbar; it now resolves only userNavigation (role badge + logo-home logic retained for signed-in operators on public routes). Build passes.

## What to build

With both operator sections migrated to the sidebar (#01, #02), simplify the global top `Navbar` so it serves only the customer/public nav.

End-to-end behaviour:

- Remove the `adminNavigation` and `franchiseeNavigation` link arrays and the admin/franchisee role-switching logic from the `Navbar` component; it should resolve only the customer/public link set.
- Remove any now-dead role plumbing the navbar used solely to pick operator menus (leave shared auth/role context used elsewhere intact).
- Pure cleanup — no behaviour change for customer/public users.

## Acceptance criteria

- [ ] `Navbar` no longer references admin/franchisee link arrays or branches on operator roles
- [ ] Customer/public navigation behaves exactly as before
- [ ] No dead code left from the operator-nav branches; no unused imports
- [ ] `cd frontend && npm run build` passes

## Blocked by

- #01 Sidebar shell + root reframe, proven on the admin section
- #02 Franchisee section adopts the sidebar
