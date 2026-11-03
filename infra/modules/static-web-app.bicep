param name string
@description('Static Web Apps is not available in every region; eastus2 is the closest to swedencentral.')
param location string
param tags object = {}

// Free tier: no idle cost. azd deploys the built SPA to the service tagged `web`.
resource web 'Microsoft.Web/staticSites@2025-03-01' = {
  name: name
  location: location
  tags: union(tags, { 'azd-service-name': 'web' })
  sku: {
    name: 'Free'
    tier: 'Free'
  }
  properties: {}
}

output name string = web.name
output url string = 'https://${web.properties.defaultHostname}'
