import { http } from "@/utils/http";
import { API_PREFIX } from "@/api/http";

export type UserItem = {
  username: string;
  nickname: string;
  role: "admin" | "common";
  enabled: boolean;
};

export type UserListResult = {
  success: boolean;
  data: { users: UserItem[] };
  message?: string;
};

export const listUsers = () => {
  return http.request<UserListResult>("get", `${API_PREFIX}/system/users`);
};

export const createUser = (data: {
  username: string;
  nickname?: string;
  password: string;
  role: string;
  enabled: boolean;
}) => {
  return http.request("post", `${API_PREFIX}/system/users`, { data });
};

export const updateUser = (
  username: string,
  data: Partial<Pick<UserItem, "nickname" | "role" | "enabled">> & {
    password?: string;
  }
) => {
  return http.request("put", `${API_PREFIX}/system/users/${username}`, { data });
};

export const deleteUser = (username: string) => {
  return http.request("delete", `${API_PREFIX}/system/users/${username}`);
};
