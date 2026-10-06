import { http } from "@/utils/http";
import { API_PREFIX } from "@/api/http";

export type PersonItem = {
  id: number;
  name: string;
  phone: string;
  shift: string;
  department: string;
};

export type PersonOptions = {
  shifts: string[];
  departments: string[];
};

export type PersonListResult = {
  success: boolean;
  data: { persons: PersonItem[]; options: PersonOptions };
  message?: string;
};

export const listPersons = () => {
  return http.request<PersonListResult>("get", `${API_PREFIX}/system/persons`);
};

export const createPerson = (data: Omit<PersonItem, "id">) => {
  return http.request("post", `${API_PREFIX}/system/persons`, { data });
};

export const updatePerson = (id: number, data: Partial<Omit<PersonItem, "id">>) => {
  return http.request("put", `${API_PREFIX}/system/persons/${id}`, { data });
};

export const deletePerson = (id: number) => {
  return http.request("delete", `${API_PREFIX}/system/persons/${id}`);
};
