import * as React from "react";
import { ApolloProvider } from "@apollo/client";
import { Theme } from "@material-ui/core/styles";
import ActionBar from "../components/ActionBar";
import HeaderBar from "../components/HeaderBar";
import { useStylesAndTheme } from "../theme";
import { elements } from '../components/elements';
import { CapturingSuspense } from '../components/misc';
import { loadConfigSync } from '../utils/config';
import { createClient } from '../utils/graphql';
import { MainContextInterface, SearchContextInterface, ElementEntryInterface } from '../interfaces';
import { MainContext, SearchContext, ConfigContext, ActiveUrlContext } from '../contexts';
import SideBar from '../components/SideBar';
// const SideBar = React.lazy(() => import('../components/SideBar'));
const SettingsImporter = React.lazy(() => import('./SettingsImporter'));
const Help = React.lazy(() => import('./Help'));

type Props = {
  defaultPath?: string
};



function MainPage(props: Props) {
  const {defaultPath} = props;
  const {classes, theme} = useStylesAndTheme();
  const [drawerOpen, setDrawerOpen] = React.useState(true);
  const [config, setConfig] = React.useState(() => loadConfigSync());
  const [mainCtx, setMainCtx] = React.useState({
    "action": config ? "add" : "start",
    "state": "default",
    "title": null,
    "item": null,
    "url": null,
    "type": null
  } as MainContextInterface);
  const [activeItem, setActiveItem] = React.useState(() => elements.keys().next().value);
  const [searchCtx, setSearchCtx] = React.useState({
    "cluster": null,
    "include": [],
    "exclude": []
  } as SearchContextInterface);
  const [activeUrl, setActiveUrl] = React.useState(() => (config ? config.baseUrl : defaultPath) as string)
  let frameElement = null;
  switch(mainCtx.action){
    case "view":
    case "add":
    case "update":
      let FrameElementWrapper = elements.get(mainCtx.type ? mainCtx.type : "undefined");
      if (!FrameElementWrapper){
        FrameElementWrapper = elements.get("undefined") as ElementEntryInterface;
      }
      const FrameElementType = (FrameElementWrapper as ElementEntryInterface).component;
      if (activeUrl === mainCtx.url || !mainCtx.url){
        frameElement = (
          <FrameElementType/>
        );
      } else {
        frameElement = (
          <ApolloProvider client={createClient(mainCtx.url)}>
            <FrameElementType/>
          </ApolloProvider>
        );
      }
      break;
    case "start":
    case "import":
      frameElement = (
        <SettingsImporter/>
      );
      break;
    case "help":
      frameElement = (
        <Help/>
      );
      break;
  }
  return (
    <ActiveUrlContext.Provider value={{activeUrl, setActiveUrl}}>
      <MainContext.Provider value={{mainCtx, setMainCtx}}>
        <SearchContext.Provider value={{searchCtx, setSearchCtx}}>
          <ConfigContext.Provider value={{config, setConfig}}>
            <ApolloProvider client={createClient(activeUrl)}>
              <div className={classes.root}>
                <SideBar
                  openState={{drawerOpen, setDrawerOpen}}
                />
                <div className={classes.subRoot}>
                  <HeaderBar
                    openState={{drawerOpen: !!(drawerOpen && config), setDrawerOpen}}
                  />
                  <main className={classes.content}>
                    <ActionBar
                    />
                    <section className={classes.mainSection}>
                      <CapturingSuspense>
                        {frameElement}
                      </CapturingSuspense>
                    </section>
                  </main>
                </div>
              </div>
            </ApolloProvider>
          </ConfigContext.Provider>
        </SearchContext.Provider>
      </MainContext.Provider>
    </ActiveUrlContext.Provider>
  );
};


export default MainPage;
