// ---------------------------------------------------------------------------
// PlagiarismGuard — Azure Infrastructure
// Deploys: App Service Plan (Linux B1) + Web App (Python 3.13)
// ---------------------------------------------------------------------------

targetScope = 'resourceGroup'

@description('Base name used for all resources')
param appName string = 'plagiarismguard'

@description('Azure region for all resources')
param location string = resourceGroup().location

@description('App Service Plan SKU')
@allowed(['B1', 'B2', 'B3', 'S1', 'S2', 'S3', 'P1v3', 'P2v3'])
param skuName string = 'B1'

@description('Python version for the Web App runtime')
param pythonVersion string = '3.13'

@description('Bing API key for web search tool (optional)')
@secure()
param bingApiKey string = ''

// ---------------------------------------------------------------------------
// Naming
// ---------------------------------------------------------------------------
var uniqueSuffix = uniqueString(resourceGroup().id)
var webAppName = '${appName}-${uniqueSuffix}'
var appServicePlanName = '${appName}-plan-${uniqueSuffix}'

// ---------------------------------------------------------------------------
// App Service Plan — Linux
// ---------------------------------------------------------------------------
resource appServicePlan 'Microsoft.Web/serverfarms@2024-04-01' = {
  name: appServicePlanName
  location: location
  kind: 'linux'
  sku: {
    name: skuName
  }
  properties: {
    reserved: true // Required for Linux
  }
}

// ---------------------------------------------------------------------------
// Web App — Python on Linux
// ---------------------------------------------------------------------------
resource webApp 'Microsoft.Web/sites@2024-04-01' = {
  name: webAppName
  location: location
  properties: {
    serverFarmId: appServicePlan.id
    httpsOnly: true
    siteConfig: {
      linuxFxVersion: 'PYTHON|${pythonVersion}'
      alwaysOn: true
      ftpsState: 'Disabled'
      minTlsVersion: '1.2'
      http20Enabled: true
      appCommandLine: 'startup.sh'
      appSettings: [
        {
          name: 'SCM_DO_BUILD_DURING_DEPLOYMENT'
          value: 'true'
        }
        {
          name: 'PG_LOG_LEVEL'
          value: 'INFO'
        }
        {
          name: 'PG_BING_API_KEY'
          value: bingApiKey
        }
      ]
    }
  }
}

// ---------------------------------------------------------------------------
// Outputs
// ---------------------------------------------------------------------------
output webAppName string = webApp.name
output webAppUrl string = 'https://${webApp.properties.defaultHostName}'
output appServicePlanName string = appServicePlan.name
