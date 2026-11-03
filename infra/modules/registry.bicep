param name string
param location string
param tags object = {}

resource registry 'Microsoft.ContainerRegistry/registries@2026-09-01-preview' = {
  name: name
  location: location
  tags: tags
  sku: { name: 'Basic' }
  properties: {
    adminUserEnabled: false
  }
}

output name string = registry.name
output id string = registry.id
output loginServer string = registry.properties.loginServer
