// Assigns one built-in role at the scope of the resource group this module deploys to.
// The caller sets `scope:` on the module call. Plan 2 reuses it.
param principalId string

@description('Built-in role definition GUID, never the role name.')
param roleDefinitionId string

@allowed(['ServicePrincipal', 'User'])
param principalType string

resource assignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(resourceGroup().id, principalId, roleDefinitionId)
  properties: {
    principalId: principalId
    principalType: principalType
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roleDefinitionId)
  }
}
