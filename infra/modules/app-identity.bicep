// A user-assigned identity that holds AcrPull on the registry. A Container App cannot use its own
// system-assigned identity to pull its image, because the role assignment needs the principal id
// while the app must depend on the assignment (circular). Create this first, name its id in
// `registries[].identity`, and make the app depend on this module. Plan 2 reuses it for the API.
param name string
param location string
param tags object = {}
param registryName string

var acrPullRoleId = '7f951dda-4ed3-4680-a7ca-43fe172d538d'

resource registry 'Microsoft.ContainerRegistry/registries@2026-09-01-preview' existing = {
  name: registryName
}

resource identity 'Microsoft.ManagedIdentity/userAssignedIdentities@2024-11-30' = {
  name: name
  location: location
  tags: tags
}

resource acrPull 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: registry
  name: guid(registry.id, identity.id, acrPullRoleId)
  properties: {
    principalId: identity.properties.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', acrPullRoleId)
  }
}

output id string = identity.id
output principalId string = identity.properties.principalId
