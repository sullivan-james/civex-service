import { api } from "./client";

const base = (owner: string, name: string) => `/api/v1/repos/${owner}/${name}`;

// Schemas
export const listSchemas = (owner: string, name: string) =>
  api.get(`${base(owner, name)}/schemas`).then((r) => r.data);

export const getSchema = (owner: string, name: string, schema: string) =>
  api.get(`${base(owner, name)}/schemas/${schema}`).then((r) => r.data);

// Datasets
export const listDatasets = (owner: string, name: string) =>
  api.get(`${base(owner, name)}/datasets`).then((r) => r.data);

// Records
export const listRecords = (
  owner: string,
  name: string,
  dataset: string,
  params?: { schema?: string; limit?: number; offset?: number }
) =>
  api
    .get(`${base(owner, name)}/datasets/${dataset}/records`, { params })
    .then((r) => r.data);

export const getRecord = (owner: string, name: string, recordId: string) =>
  api.get(`${base(owner, name)}/records/${recordId}`).then((r) => r.data);

export const updateRecord = (
  owner: string,
  name: string,
  recordId: string,
  data: Record<string, unknown>
) => api.patch(`${base(owner, name)}/records/${recordId}`, { data }).then((r) => r.data);

export const deleteRecord = (owner: string, name: string, recordId: string) =>
  api.delete(`${base(owner, name)}/records/${recordId}`);

// Commits & audit
export const listCommits = (owner: string, name: string, params?: { limit?: number; offset?: number }) =>
  api.get(`${base(owner, name)}/commits`, { params }).then((r) => r.data);

export const getCommitAudit = (owner: string, name: string, commitId: string) =>
  api.get(`${base(owner, name)}/commits/${commitId}/audit`).then((r) => r.data);

export const getAuditLog = (
  owner: string,
  name: string,
  params?: { entity_type?: string; entity_id?: string; limit?: number }
) =>
  api.get(`${base(owner, name)}/audit`, { params }).then((r) => r.data);

// Record children
export const getRecordChildren = (owner: string, name: string, recordId: string) =>
  api.get(`${base(owner, name)}/records/${recordId}/children`).then((r) => r.data);

// Schema access
export const listSchemaAccess = (owner: string, name: string, schemaName: string) =>
  api.get(`${base(owner, name)}/schemas/${schemaName}/access`).then((r) => r.data);

export const grantSchemaAccess = (
  owner: string, name: string, schemaName: string,
  body: { subject_type: string; subject_id?: string; role: string }
) =>
  api.post(`${base(owner, name)}/schemas/${schemaName}/access`, body).then((r) => r.data);

export const revokeSchemaAccess = (owner: string, name: string, schemaName: string, grantId: string) =>
  api.delete(`${base(owner, name)}/schemas/${schemaName}/access/${grantId}`);

export const listFieldAccess = (owner: string, name: string, schemaName: string, fieldId: string) =>
  api.get(`${base(owner, name)}/schemas/${schemaName}/fields/${fieldId}/access`).then((r) => r.data);

export const grantFieldAccess = (
  owner: string, name: string, schemaName: string, fieldId: string,
  body: { subject_type: string; subject_id?: string; can_read: boolean; can_write: boolean }
) =>
  api.post(`${base(owner, name)}/schemas/${schemaName}/fields/${fieldId}/access`, body).then((r) => r.data);

export const revokeFieldAccess = (
  owner: string, name: string, schemaName: string, fieldId: string, grantId: string
) =>
  api.delete(`${base(owner, name)}/schemas/${schemaName}/fields/${fieldId}/access/${grantId}`);

// Dataset access
export const listDatasetAccess = (owner: string, name: string, datasetName: string) =>
  api.get(`${base(owner, name)}/datasets/${datasetName}/access`).then((r) => r.data);

export const grantDatasetAccess = (
  owner: string, name: string, datasetName: string,
  body: { subject_type: string; subject_id?: string; role: string }
) =>
  api.post(`${base(owner, name)}/datasets/${datasetName}/access`, body).then((r) => r.data);

export const revokeDatasetAccess = (owner: string, name: string, datasetName: string, grantId: string) =>
  api.delete(`${base(owner, name)}/datasets/${datasetName}/access/${grantId}`);
