// Assigns one built-in role on a single Foundry resource. Pass the role as a GUID, never a name.
// Plan 2 reuses it.
param resourceName string
param principalId string

@description('Built-in role definition GUID, never the role name.')
param roleDefinitionId string

@allowed(['ServicePrincipal', 'User'])
param principalType string

resource target 'Microsoft.CognitiveServices/accounts@2025-06-01' existing = {
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
