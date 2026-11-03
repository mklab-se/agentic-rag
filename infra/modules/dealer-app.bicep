param name string
param location string
param tags object = {}
param environmentId string
param registryLoginServer string
param pullIdentityId string
param tenantId string
param dealerClientId string
param appInsightsConnectionString string

// The system-assigned identity is for service auth; the user-assigned one only pulls the image.
// The caller must make this module depend on the pull identity's AcrPull assignment.
resource dealer 'Microsoft.App/containerApps@2025-01-01' = {
  name: name
  location: location
  tags: union(tags, { 'azd-service-name': 'dealer' })
  identity: {
    type: 'SystemAssigned,UserAssigned'
    userAssignedIdentities: { '${pullIdentityId}': {} }
  }
  properties: {
    managedEnvironmentId: environmentId
    configuration: {
      activeRevisionsMode: 'Single'
      ingress: {
        external: true
        targetPort: 8000
        transport: 'auto'
        allowInsecure: false
      }
      registries: [
        {
          server: registryLoginServer
          identity: pullIdentityId
        }
      ]
    }
    template: {
      containers: [
        {
          name: 'dealer'
          image: 'mcr.microsoft.com/k8se/quickstart:latest' // placeholder, azd deploy swaps the image
          resources: {
            cpu: json('0.5')
            memory: '1Gi'
          }
          env: [
            { name: 'TENANT_ID', value: tenantId }
            { name: 'DEALER_CLIENT_ID', value: dealerClientId }
            { name: 'APPLICATIONINSIGHTS_CONNECTION_STRING', value: appInsightsConnectionString }
            { name: 'LOG_LEVEL', value: 'INFO' }
          ]
        }
      ]
      scale: {
        minReplicas: 0
        maxReplicas: 2
      }
    }
  }
}

output name string = dealer.name
output url string = 'https://${dealer.properties.configuration.ingress.fqdn}'
output principalId string = dealer.identity.principalId
