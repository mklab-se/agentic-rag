// Assigns one built-in role on a single storage resource. Pass the role as a GUID, never a name.
// The API and the agents use it too.
param resourceName string
param principalId string

@description('Built-in role definition GUID, never the role name.')
param roleDefinitionId string

@allowed(['ServicePrincipal', 'User'])
param principalType string

resource target 'Microsoft.Storage/storageAccounts@2026-09-01' existing = {
  name: resourceName
}

resource assignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: target
  name: guid(target.id, principalId, roleDefinitionId)
  properties: {
    principalId: principalId
    principalType: principalType
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roleDefinitionId)
  }
}
