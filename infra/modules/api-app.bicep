param name string
param location string
param tags object = {}
param environmentId string
param registryLoginServer string
@description('Image to run. The placeholder listens on 8000 via ASPNETCORE_HTTP_PORTS; azd deploy swaps it.')
param image string
param pullIdentityId string
param tenantId string
param apiClientId string
param dealerUrl string
param dealerClientId string
param foundryProjectEndpoint string
param chatDeployment string
param searchEndpoint string
param kbConnectionName string
param promptAgentCli string
param promptAgentWeb string
param hostedAgentName string
@description('Comma separated list of allowed browser origins.')
param corsOrigins string
param appInsightsConnectionString string

// The system-assigned identity calls Foundry, Search and the dealer; the user-assigned one only
// pulls the image. AZURE_CLIENT_ID is deliberately not set, so DefaultAzureCredential picks the
// system identity. The caller must make this module depend on the pull identity's AcrPull assignment.
// Ingress does not buffer responses, so server-sent events stream through; Container Apps closes
// idle connections after 240 seconds (not configurable), so the API sends SSE keep-alives.
resource api 'Microsoft.App/containerApps@2026-07-01' = {
  name: name
  location: location
  tags: union(tags, { 'azd-service-name': 'api' })
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
          name: 'api'
          image: image
          resources: {
            cpu: json('0.5')
            memory: '1Gi'
          }
          env: [
            { name: 'TENANT_ID', value: tenantId }
            { name: 'API_CLIENT_ID', value: apiClientId }
            { name: 'DEALER_URL', value: dealerUrl }
            { name: 'DEALER_CLIENT_ID', value: dealerClientId }
            { name: 'FOUNDRY_PROJECT_ENDPOINT', value: foundryProjectEndpoint }
            { name: 'CHAT_DEPLOYMENT', value: chatDeployment }
            { name: 'SEARCH_ENDPOINT', value: searchEndpoint }
            { name: 'KB_CONNECTION_NAME', value: kbConnectionName }
            { name: 'PROMPT_AGENT_CLI', value: promptAgentCli }
            { name: 'PROMPT_AGENT_WEB', value: promptAgentWeb }
            { name: 'HOSTED_AGENT_NAME', value: hostedAgentName }
            { name: 'CORS_ORIGINS', value: corsOrigins }
            { name: 'AGENT_BACKEND', value: 'loop' }
            { name: 'APPLICATIONINSIGHTS_CONNECTION_STRING', value: appInsightsConnectionString }
            { name: 'LOG_LEVEL', value: 'INFO' }
            { name: 'ASPNETCORE_HTTP_PORTS', value: '8000' } // only used by the placeholder image
          ]
        }
      ]
      scale: {
        minReplicas: 0
        maxReplicas: 1
      }
    }
  }
}

output name string = api.name
output url string = 'https://${api.properties.configuration.ingress.fqdn}'
output principalId string = api.identity.principalId
