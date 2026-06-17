---
title: Groups and RBAC
description: Access boundaries, group roles, team roles and permissions.
---

# Groups and RBAC

IncidentRelay uses two permission layers:

1. **Group roles** define the access boundary and group-level administration.
2. **Team roles** define what a user can do inside a specific team.

A user must belong to a group before they can belong to a team in that group. Adding a user to a team does **not** add the user to the group automatically.

## Global admin

A global admin can manage the whole installation:

- create, update and delete groups;
- create and manage users;
- add existing users to groups;
- assign any group role, including `user_admin`;
- manage all teams and resources;
- view all data.

A global admin should not be able to delete or disable themselves, and the system should keep at least one active global admin.

## Group roles

| Role | UI label | Purpose |
|---|---|---|
| `viewer` | Group Viewer | Can see resources inside the group boundary |
| `editor` | Group Editor | Can create or edit group-level operational resources, for example create a team in the group |
| `user_admin` | Group Admin | Can create and manage users only inside this group boundary |


### Group Admin boundaries

`user_admin` is intentionally limited:

- can create a new user only inside the selected group;
- the created user is automatically linked to that group;
- cannot pass or override `group_id` in request body;
- cannot create a global admin user;
- cannot assign another `user_admin`;
- cannot add an existing user to a group;
- cannot move a user between groups;
- cannot globally disable or delete a user.

### Group Editor boundaries

`editor` is an operational group-level role.

A Group Editor can:

- create teams inside the group;
- create and edit group-level operational resources;
- manage a team only when they also have the `manager` role in that team.

A Group Editor cannot:

- manage users;
- assign group roles;
- assign `user_admin`;
- manage every team in the group automatically;
- edit rotations, routes, services, channels or silences of a team where they are not a Team Manager.

When a Group Editor creates a new team, IncidentRelay adds that user as `manager` of the created team.

Adding an existing user to a group changes the group boundary and is global-admin only.

## Team roles

| Role | UI label | Purpose |
|---|---|---|
| `viewer` | Team Viewer | Can see team resources and alerts |
| `responder` | Team Responder | Can see team resources and acknowledge or resolve alerts |
| `manager` | Team Manager | Can manage team resources, team users, channels, routes, rotations and silences |

A group `editor` does not automatically become manager of every team in the group. Team write access requires the `manager` team role.

When a non-admin group `editor` creates a new team, IncidentRelay should add that creator as `manager` of the created team.

## Permission matrix

| Action | Required permission |
|---|---|
| List visible groups | Any active group membership or global admin |
| Create group | Global admin |
| Update group properties | Group `editor` or global admin |
| Delete group | Global admin |
| List group users | Group readable membership or global admin |
| Create a user inside a group | Group `user_admin` or global admin |
| Add existing user to group | Global admin |
| Assign group roles | Group `user_admin` with restrictions, or global admin |
| Assign `user_admin` role | Global admin |
| Disable group membership | Group `user_admin` or global admin |
| Remove group membership | Global admin |
| Create team in group | Group `editor` or global admin |
| Read team | Team `viewer`, `responder`, `manager` or global admin |
| Acknowledge or resolve alert | Team `responder`, `manager` or global admin |
| Manage team resources | Team `manager` or global admin |
| Add user to team | Team `manager` or global admin; target user must already be in the team group |
| Manage own created team | Team `manager` or global admin |
| Manage any team in group | Not allowed by group role alone; requires Team `manager` |
| Manage rotations | Team `manager` or global admin |
| Manage routes | Team `manager` or global admin |
| Manage services | Team `manager` or global admin |
| Manage channels | Team `manager` or global admin |
| Manage silences | Team `manager` or global admin |
