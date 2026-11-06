param name string
param location string
param tags object = {}

resource search 'Microsoft.Search/searchServices@2026-09-01-preview' = {
  name: name
  location: location
  tags: tags
  sku: { name: 'basic' }
  identity: { type: 'SystemAssigned' }
  properties: {
    replicaCount: 1
    partitionCount: 1
    hostingMode: 'Default'
    semanticSearch: 'standard'
    // The free plan refuses every retrieve with 402 once its monthly allowance is used.
    knowledgeRetrieval: 'standard'
    disableLocalAuth: true
    publicNetworkAccess: 'enabled'
  }
}

output name string = search.name
output endpoint string = 'https://${search.name}.search.windows.net'
output principalId string = search.identity.principalId
