param name string
param location string
param tags object = {}
param environmentId string
param registryLoginServer string
@description('Image to run. The placeholder listens on 8000 via ASPNETCORE_HTTP_PORTS; azd deploy swaps it.')
param image string
param pullIdentityId string
param tenantId string
param dealerClientId string
param appInsightsConnectionString string

// The system-assigned identity is for service auth; the user-assigned one only pulls the image.
// The caller must make this module depend on the pull identity's AcrPull assignment.
resource dealer 'Microsoft.App/containerApps@2026-07-01' = {
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
          image: image
          resources: {
            cpu: json('0.5')
            memory: '1Gi'
          }
          env: [
            { name: 'TENANT_ID', value: tenantId }
            { name: 'DEALER_CLIENT_ID', value: dealerClientId }
            { name: 'APPLICATIONINSIGHTS_CONNECTION_STRING', value: appInsightsConnectionString }
            { name: 'OTEL_SERVICE_NAME', value: 'voltrieve-dealer' }
            { name: 'LOG_LEVEL', value: 'INFO' }
            { name: 'ASPNETCORE_HTTP_PORTS', value: '8000' } // only used by the placeholder image
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
