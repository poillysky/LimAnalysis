import { http } from "@/utils/http";
import { API_PREFIX } from "@/api/http";

export type DutyType = "白班" | "夜班";

export type RosterPerson = {
  id: number;
  name: string;
  phone: string;
  department: string;
};

export type RosterEntry = {
  id: number;
  person_id: number | null;
  name: string;
  duty: DutyType;
  machines: string[];
};

export type RosterListResult = {
  success: boolean;
  data: {
    entries: RosterEntry[];
    duties: DutyType[];
    machines: string[];
    persons: RosterPerson[];
  };
  message?: string;
};

export const listDutyRoster = () => {
  return http.request<RosterListResult>("get", `${API_PREFIX}/system/duty-roster`);
};

export const createDutyRoster = (data: {
  person_id?: number | null;
  name?: string;
  duty: DutyType;
  machines: string[];
}) => {
  return http.request("post", `${API_PREFIX}/system/duty-roster`, { data });
};

export const updateDutyRoster = (
  id: number,
  data: Partial<{
    person_id: number | null;
    name: string;
    duty: DutyType;
    machines: string[];
  }>
) => {
  return http.request("put", `${API_PREFIX}/system/duty-roster/${id}`, { data });
};

export const deleteDutyRoster = (id: number) => {
  return http.request("delete", `${API_PREFIX}/system/duty-roster/${id}`);
};
