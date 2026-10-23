// RBAC-02, RBAC-04: User role assignments with brand scopes. GET/POST/DELETE /api/admin/user-roles.

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import type { UserRole } from "../api/types";
import { Empty, ErrorBox, Spinner, useToast } from "../components/Common";

const SEED_ROLES = [
  "pim_admin",
  "product_manager",
  "merchandiser",
  "ecommerce_manager",
  "channel_manager",
  "copywriter",
  "design_tech",
  "viewer",
];

export function UserRolesTab() {
  const qc = useQueryClient();
  const toast = useToast();
  const q = useQuery({ queryKey: ["admin", "user-roles"], queryFn: api.admin.userRoles });
  const [email, setEmail] = useState("");
  const [role, setRole] = useState(SEED_ROLES[1]);
  const [customRole, setCustomRole] = useState("");
  const [scopes, setScopes] = useState("");

  const add = useMutation({
    mutationFn: () =>
      api.admin.addUserRole({
        email: email.trim(),
        role: role === "__custom" ? customRole.trim() : role,
        brand_scopes: scopes.split(/[,\s]+/).map((s) => s.trim()).filter(Boolean),
      }),
    onSuccess: () => {
      toast("Role assigned", "ok");
      setEmail("");
      setScopes("");
      qc.invalidateQueries({ queryKey: ["admin", "user-roles"] });
    },
    onError: (e) => toast(`Could not assign role: ${(e as Error).message}`, "error"),
  });
  const remove = useMutation({
    mutationFn: (r: UserRole) => api.admin.removeUserRole({ id: r.id, email: r.email, role: r.role }),
    onSuccess: () => {
      toast("Role removed", "ok");
      qc.invalidateQueries({ queryKey: ["admin", "user-roles"] });
    },
    onError: (e) => toast(`Could not remove role: ${(e as Error).message}`, "error"),
  });

  return (
    <div>
      <div className="panel mb16">
        <div className="panel-body">
          <form
            className="row"
            onSubmit={(e) => {
              e.preventDefault();
              add.mutate();
            }}
          >
            <input type="email" required placeholder="user@swimusa.com" value={email} onChange={(e) => setEmail(e.target.value)} style={{ width: 240 }} />
            <select value={role} onChange={(e) => setRole(e.target.value)}>
              {SEED_ROLES.map((r) => (
                <option key={r} value={r}>
                  {r}
                </option>
              ))}
              <option value="__custom">other role</option>
            </select>
            {role === "__custom" && <input placeholder="role code" value={customRole} onChange={(e) => setCustomRole(e.target.value)} />}
            <input placeholder="Brand scopes, comma separated (empty = all brands)" value={scopes} onChange={(e) => setScopes(e.target.value)} style={{ width: 300 }} />
            <button className="primary" type="submit" disabled={add.isPending || !email.trim() || (role === "__custom" && !customRole.trim())}>
              Assign
            </button>
          </form>
          <div className="help mt8">
            Roles grant features; data rights per attribute group come from the group's owning role. Brand scopes limit which products a
            user sees, defined as a rule over ERP fields (RBAC-04).
          </div>
        </div>
      </div>
      {q.isLoading && <Spinner label="Loading role assignments" />}
      {q.isError && <ErrorBox error={q.error} title="Could not load user roles" />}
      {q.data && q.data.length === 0 && <Empty title="No role assignments">Assign the first PIM admin above.</Empty>}
      {q.data && q.data.length > 0 && (
        <div className="panel">
          <table className="data">
            <thead>
              <tr>
                <th>Email</th>
                <th>Role</th>
                <th>Brand scopes</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {q.data
                .slice()
                .sort((a, b) => a.email.localeCompare(b.email) || a.role.localeCompare(b.role))
                .map((r, i) => (
                  <tr key={r.id ?? `${r.email}:${r.role}:${i}`}>
                    <td>{r.email}</td>
                    <td className="mono">{r.role}</td>
                    <td>
                      <div className="chips">
                        {r.brand_scopes.length === 0 ? (
                          <span className="faint">all brands</span>
                        ) : (
                          r.brand_scopes.map((b) => (
                            <span key={b} className="badge teal">
                              {b}
                            </span>
                          ))
                        )}
                      </div>
                    </td>
                    <td>
                      <button className="small danger" disabled={remove.isPending} onClick={() => remove.mutate(r)}>
                        Remove
                      </button>
                    </td>
                  </tr>
                ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
