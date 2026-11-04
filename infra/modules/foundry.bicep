param name string
param location string
param tags object = {}
param projectName string
param appInsightsName string
param chatModelName string
param chatModelVersion string
param embeddingModelName string
param embeddingModelVersion string

resource appInsights 'Microsoft.Insights/components@2020-02-02' existing = {
  name: appInsightsName
}

resource account 'Microsoft.CognitiveServices/accounts@2026-09-15-preview' = {
  name: name
  location: location
  tags: tags
  kind: 'AIServices'
  sku: { name: 'S0' }
  identity: { type: 'SystemAssigned' }
  properties: {
    allowProjectManagement: true
    customSubDomainName: name
    disableLocalAuth: true
    publicNetworkAccess: 'Enabled'
  }
}

resource project 'Microsoft.CognitiveServices/accounts/projects@2026-09-15-preview' = {
  parent: account
  name: projectName
  location: location
  tags: tags
  identity: { type: 'SystemAssigned' }
  properties: {
    displayName: projectName
  }
}

resource chatDeployment 'Microsoft.CognitiveServices/accounts/deployments@2026-09-15-preview' = {
  parent: account
  name: chatModelName
  dependsOn: [project]
  sku: {
    name: 'GlobalStandard'
    capacity: 50
  }
  properties: {
    model: {
      format: 'OpenAI'
      name: chatModelName
      version: chatModelVersion
    }
  }
}

// Chained with dependsOn: the service rejects concurrent deployment writes on one account.
resource embeddingDeployment 'Microsoft.CognitiveServices/accounts/deployments@2026-09-15-preview' = {
  parent: account
  name: embeddingModelName
  dependsOn: [chatDeployment]
  sku: {
    name: 'GlobalStandard'
    capacity: 10
  }
  properties: {
    model: {
      format: 'OpenAI'
      name: embeddingModelName
      version: embeddingModelVersion
    }
  }
}

// The App Insights connection string is an ingestion endpoint identifier, not a secret.
resource appInsightsConnection 'Microsoft.CognitiveServices/accounts/projects/connections@2026-09-15-preview' = {
  parent: project
  name: 'appinsights'
  properties: {
    category: 'AppInsights'
    target: appInsights.id
    authType: 'ApiKey' // connection string is an ingestion identifier, not an application secret
    isSharedToAll: true
    credentials: {
      key: appInsights.properties.ConnectionString
    }
    metadata: {
      ApiType: 'Azure'
      ResourceId: appInsights.id
    }
  }
}

output name string = account.name
output id string = account.id
output principalId string = account.identity.principalId
output endpoint string = 'https://${account.name}.services.ai.azure.com'
output openAiEndpoint string = 'https://${account.name}.openai.azure.com'
output projectEndpoint string = 'https://${account.name}.services.ai.azure.com/api/projects/${project.name}'
output projectName string = project.name
output projectPrincipalId string = project.identity.principalId
output chatDeployment string = chatDeployment.name
output embeddingDeployment string = embeddingDeployment.name
