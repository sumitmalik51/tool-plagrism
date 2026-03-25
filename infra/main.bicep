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

@description('Comma-separated API keys for service-to-service auth')
@secure()
param apiKeys string = ''

@description('Entra ID (Azure AD) tenant ID for Easy Auth')
param entraIdTenantId string = ''

@description('Entra ID client (application) ID for Easy Auth')
param entraIdClientId string = ''

@description('Azure Communication Services connection string for sending emails')
@secure()
param acsConnectionString string = ''

@description('Sender email address from the ACS Email domain')
param acsSenderEmail string = 'DoNotReply@plagiarismguard.com'

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
      appCommandLine: 'bash /home/site/wwwroot/startup.sh'
      appSettings: [
        {
          name: 'SCM_DO_BUILD_DURING_DEPLOYMENT'
          value: 'false'
        }
        {
          name: 'ENABLE_ORYX_BUILD'
          value: 'false'
        }
        {
          name: 'PG_LOG_LEVEL'
          value: 'INFO'
        }
        {
          name: 'PG_BING_API_KEY'
          value: bingApiKey
        }
        {
          name: 'PG_UPLOAD_DIR'
          value: '/home/uploads'
        }
        {
          name: 'PG_API_KEYS_RAW'
          value: apiKeys
        }
        {
          name: 'WEBSITES_CONTAINER_START_TIME_LIMIT'
          value: '1800'
        }
        
        {
          name: 'PG_ACS_CONNECTION_STRING'
          value: acsConnectionString
        }
        {
          name: 'PG_ACS_SENDER_EMAIL'
          value: acsSenderEmail
        }
      ]
    }
  }
}

// ---------------------------------------------------------------------------
// Authentication — Azure Easy Auth (Entra ID)
// Only deployed when both entraIdTenantId and entraIdClientId are provided.
// ---------------------------------------------------------------------------
resource authSettings 'Microsoft.Web/sites/config@2024-04-01' = if (!empty(entraIdTenantId) && !empty(entraIdClientId)) {
  parent: webApp
  name: 'authsettingsV2'
  properties: {
    globalValidation: {
      requireAuthentication: true
      unauthenticatedClientAction: 'RedirectToLoginPage'
      excludedPaths: [
        '/health'
        '/openai-foundry.json'
        '/api/v1/*'   // API routes use X-API-Key instead
      ]
    }
    identityProviders: {
      azureActiveDirectory: {
        enabled: true
        registration: {
          clientId: entraIdClientId
          openIdIssuer: 'https://sts.windows.net/${entraIdTenantId}/v2.0'
        }
        validation: {
          allowedAudiences: [
            'api://${entraIdClientId}'
          ]
        }
      }
    }
    platform: {
      enabled: true
    }
  }
}

// ---------------------------------------------------------------------------
// Outputs
// ---------------------------------------------------------------------------
output webAppName string = webApp.name
output webAppUrl string = 'https://${webApp.properties.defaultHostName}'
output appServicePlanName string = appServicePlan.name
