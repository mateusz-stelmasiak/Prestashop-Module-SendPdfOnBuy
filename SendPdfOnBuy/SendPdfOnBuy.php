<?php
/**
 * 2007-2022 PrestaShop
 *
 * NOTICE OF LICENSE
 *
 * This source file is subject to the Academic Free License (AFL 3.0)
 * that is bundled with this package in the file LICENSE.txt.
 * It is also available through the world-wide-web at this URL:
 * http://opensource.org/licenses/afl-3.0.php
 * If you did not receive a copy of the license and are unable to
 * obtain it through the world-wide-web, please send an email
 * to license@prestashop.com so we can send you a copy immediately.
 *
 * DISCLAIMER
 *
 * Do not edit or add to this file if you wish to upgrade PrestaShop to newer
 * versions in the future. If you wish to customize PrestaShop for your
 * needs please refer to http://www.prestashop.com for more information.
 *
 * @author    PrestaShop SA <contact@prestashop.com>
 * @copyright 2007-2022 PrestaShop SA
 * @license   http://opensource.org/licenses/afl-3.0.php  Academic Free License (AFL 3.0)
 *  International Registered Trademark & Property of PrestaShop SA
 */

if (!defined('_PS_VERSION_')) {
    exit;
}

class SendPdfOnBuy extends Module
{
    protected $config_form = false;

    public function __construct()
    {
        $this->name = 'SendPdfOnBuy';
        $this->tab = 'emailing';
        $this->version = '1.0.0';
        $this->author = 'Mateusz Stelmasiak';
        $this->need_instance = 0;

        /**
         * Set $this->bootstrap to true if your module is compliant with bootstrap (PrestaShop 1.6)
         */
        $this->bootstrap = true;

        parent::__construct();

        $this->displayName = $this->l('Send on buy');
        $this->description = $this->l('Allows you to choose a pdf file to be sent to a client once he buys certain products.');

        $this->ps_versions_compliancy = array('min' => '1.6', 'max' => _PS_VERSION_);

        if (!$this->isRegisteredInHook('actionOrderStatusPostUpdate'))
            $this->registerHook('actionOrderStatusPostUpdate');
    }

    /**
     * Don't forget to create update methods if needed:
     * http://doc.prestashop.com/display/PS16/Enabling+the+Auto-Update
     */
    public function install()
    {
        Configuration::updateValue('SENDPDFONBUY_LIVE_MODE', false);

        include(dirname(__FILE__) . '/sql/install.php');

        return parent::install() &&
            $this->registerHook('header') &&
            $this->registerHook('backOfficeHeader') &&
            $this->registerHook('actionOrderStatusPostUpdate');
    }

    public function uninstall()
    {
        Configuration::deleteByName('SENDPDFONBUY_LIVE_MODE');

        include(dirname(__FILE__) . '/sql/uninstall.php');

        return parent::uninstall();
    }

    /**
     * Load the configuration form
     */
    public function getContent()
    {
        /**
         * If values have been submitted in the form, process.
         */
        if (((bool)Tools::isSubmit('submitSendPdfOnBuyModule')) == true) {
            $this->postProcess();
        }

        $this->context->smarty->assign('module_dir', $this->_path);

        $output = $this->context->smarty->fetch($this->local_path . 'views/templates/admin/configure.tpl');

        return $output;
    }

    /**
     * Create the form that will be displayed in the configuration of your module.
     */
    protected function renderForm()
    {
        $helper = new HelperForm();

        $helper->show_toolbar = false;
        $helper->table = $this->table;
        $helper->module = $this;
        $helper->default_form_language = $this->context->language->id;
        $helper->allow_employee_form_lang = Configuration::get('PS_BO_ALLOW_EMPLOYEE_FORM_LANG', 0);

        $helper->identifier = $this->identifier;
        $helper->submit_action = 'submitSendPdfOnBuyModule';
        $helper->currentIndex = $this->context->link->getAdminLink('AdminModules', false)
            . '&configure=' . $this->name . '&tab_module=' . $this->tab . '&module_name=' . $this->name;
        $helper->token = Tools::getAdminTokenLite('AdminModules');

        $helper->tpl_vars = array(
            'fields_value' => $this->getConfigFormValues(), /* Add values for your inputs */
            'languages' => $this->context->controller->getLanguages(),
            'id_language' => $this->context->language->id,
        );

        return $helper->generateForm(array($this->getConfigForm()));
    }

    /**
     * Create the structure of your form.
     */
    protected function getConfigForm()
    {
        return array(
            'form' => array(
                'legend' => array(
                    'title' => $this->l('Settings'),
                    'icon' => 'icon-cogs',
                ),
                'input' => array(
                    array(
                        'type' => 'switch',
                        'label' => $this->l('Live mode'),
                        'name' => 'SENDPDFONBUY_LIVE_MODE',
                        'is_bool' => true,
                        'desc' => $this->l('Use this module in live mode'),
                        'values' => array(
                            array(
                                'id' => 'active_on',
                                'value' => true,
                                'label' => $this->l('Enabled')
                            ),
                            array(
                                'id' => 'active_off',
                                'value' => false,
                                'label' => $this->l('Disabled')
                            )
                        ),
                    ),
                    array(
                        'col' => 3,
                        'type' => 'text',
                        'prefix' => '<i class="icon icon-envelope"></i>',
                        'desc' => $this->l('Enter a valid email address'),
                        'name' => 'SENDPDFONBUY_ACCOUNT_EMAIL',
                        'label' => $this->l('Email'),
                    ),
                    array(
                        'type' => 'password',
                        'name' => 'SENDPDFONBUY_ACCOUNT_PASSWORD',
                        'label' => $this->l('Password'),
                    ),
                ),
                'submit' => array(
                    'title' => $this->l('Save'),
                ),
            ),
        );
    }

    /**
     * Set values for the inputs.
     */
    protected function getConfigFormValues()
    {
        return array(
            'SENDPDFONBUY_LIVE_MODE' => Configuration::get('SENDPDFONBUY_LIVE_MODE', true),
            'SENDPDFONBUY_ACCOUNT_EMAIL' => Configuration::get('SENDPDFONBUY_ACCOUNT_EMAIL', 'contact@prestashop.com'),
            'SENDPDFONBUY_ACCOUNT_PASSWORD' => Configuration::get('SENDPDFONBUY_ACCOUNT_PASSWORD', null),
        );
    }

    /**
     * Save form data.
     */
    protected function postProcess()
    {
        $form_values = $this->getConfigFormValues();

        foreach (array_keys($form_values) as $key) {
            Configuration::updateValue($key, Tools::getValue($key));
        }
    }

    /**
     * Add the CSS & JavaScript files you want to be loaded in the BO.
     */
    public function hookBackOfficeHeader()
    {
        if (Tools::getValue('module_name') == $this->name) {
            $this->context->controller->addJS($this->_path . 'views/js/back.js');
            $this->context->controller->addCSS($this->_path . 'views/css/back.css');
        }
    }

    /**
     * Add the CSS & JavaScript files you want to be added on the FO.
     */
    public function hookHeader()
    {
        $this->context->controller->addJS($this->_path . '/views/js/front.js');
        $this->context->controller->addCSS($this->_path . '/views/css/front.css');
    }

    public function hookActionOrderStatusPostUpdate($params)
    {
        //to handle orders from allegro
        $id_order = $params['id_order'];
        $orderStatus = $params['newOrderStatus'];

        if ($orderStatus->paid) {
            $this->sendPdfAttachments($id_order);
        }

    }

    public function getRandomString($length = 6)
    {
        $characters = '0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ';
        $string = '';

        for ($i = 0; $i < $length; $i++) {
            $string .= $characters[mt_rand(0, strlen($characters) - 1)];
        }

        return $string;
    }

    public function sendPdfAttachments($id_order)
    {
        $order = new Order($id_order);
        $products = $order->getProducts();
        //create list of ordered products for SQL query
        $productSQLList = "";
        foreach ($products as $product) {
            $productSQLList .= $product['id_product'] . ",";
        }
        if (empty($productSQLList)) return; //no products in order? better safe then sorry
        $productSQLList = substr($productSQLList, 0, -1); //removes last coma
        //get from database
        $sql = 'SELECT DISTINCT p.id_pdfAttachment,mail_title,mail_content,g.id_product FROM ' . _DB_PREFIX_ . 'pdfAttachments p 
                JOIN ' . _DB_PREFIX_ . 'pdfAttachment_product g ON ( g.id_pdfAttachment = p.id_pdfAttachment) 
                WHERE g.id_product IN (' . $productSQLList . ')';
        $emailsToSend = Db::getInstance()->executeS($sql);

        if (empty($emailsToSend)) return; //no emails to send

        //cache customer info
        $customer = $order->getCustomer();
        $customerMail = $customer->email;
        $firstname = $customer->firstname;
        $lastname = $customer->lastname;
        //iterate through all the emails that need to be sent
        foreach ($emailsToSend as $email) {
            $id_pdfAttachment = $email['id_pdfAttachment'];
            $mailTitle = $email['mail_title'];
            $mailContent = $email['mail_content'];

            //if contains voucher, generate it and add to content
            if ($id_pdfAttachment == 2) {
                //count how many voucher products the client bought
                $voucherProductId = $email['id_product'];
                $voucherProductQuantity = 0;
                foreach($products as $product){
                   if($product['id_product'] == $voucherProductId){
                       $voucherProductQuantity = $product['product_quantity'];
                   }
                }

                //generate ammount of codes equal to ammount of bought voucher items
                $voucherCodes = [];
                for($i=0;$i<$voucherProductQuantity;$i++){
                    $voucherCode = "VOUCHER_" . $this->getRandomString(6);
                    $desc = "Voucher na zakup Twojego wybranego zestawu dań z diety dr Ewy Dąbrowskiej";
                    //$customerId = $customer->id; //limits to the customer that bought it
                    $customerId = 0; //any customer can use
                    $currDate = date("Y-m-d h:i:s");
                    //expires in 6 months
                    $expDate = date('Y-m-d h:i:s', strtotime("+6 months", strtotime($currDate)));
                    $reductionProductId = 77;
                    $reductionAmmount = 300;

                    //add voucher to db
                    $sql = 'INSERT INTO ' . _DB_PREFIX_ . 'cart_rule 
                (`id_customer`, `date_from`, `date_to`, `description`, `quantity`, `quantity_per_user`, `priority`, `partial_use`, `code`, `product_restriction`,`reduction_amount`, `reduction_tax`, `reduction_currency`, `reduction_product`,`highlight`, `active`,`date_add`) 
                VALUES (' . $customerId . ',"' . $currDate . '","' . $expDate . '","' . $desc . '",1,1,1,0,"' . $voucherCode . '",1,' . $reductionAmmount . ',1,1,' . $reductionProductId . ',0,1,"' . $currDate . '")';
                    Db::getInstance()->execute($sql);
                    $idCartRule = (int) Db::getInstance()->Insert_ID();

                    //add name to cart rule
                    $values = array(
                        'id_cart_rule' => $idCartRule,
                        'id_lang' =>  Configuration::get('PS_LANG_DEFAULT'),
                        'name' => 'Voucher na zestaw',
                    );
                    Db::getInstance()->insert('cart_rule_lang', $values);

                    //add restriction to product
                    $values = array(
                        'id_cart_rule' => $idCartRule,
                        'quantity' => 1,
                    );
                    Db::getInstance()->insert('cart_rule_product_rule_group', $values);
                    $idProductRuleGroup = (int) Db::getInstance()->Insert_ID();

                    $values = array(
                        'id_product_rule_group' => $idProductRuleGroup,
                        'type' => 'products',
                    );
                    Db::getInstance()->insert('cart_rule_product_rule', $values);
                    $idProductRule = (int) Db::getInstance()->Insert_ID();

                    $values = array(
                        'id_product_rule' => $idProductRule,
                        'id_item' => $reductionProductId,
                    );
                    Db::getInstance()->insert('cart_rule_product_rule_value', $values);
                    $voucherCodes[]=$voucherCode;
                }

                if(count($voucherCodes)==1){
                    $voucherCode = $voucherCodes[0];
                    $mailContent .= "<p style='text-align:center'>Twój kod vouchera to:<br/><b>" . $voucherCode . "</b></p>";
                }
                else{
                    $mailContent .= "<p style='text-align:center'>Kody Twoich voucherów:";
                    foreach($voucherCodes as $voucherCode){
                        $mailContent .="<br/><b>" . $voucherCode . "</b>";
                    }
                    $mailContent .="</p>";
                }


                $mailContent .= "<p>
                                    Skomponuj <a href='https://alhambrasklep.pl/pl/zestawy-na-6-dniowy-post-dr-dabrowskiej/77-twoj-wlasny-zestaw.html'>Twój własny zestaw</a> i użyj kodu przy płatności! 
                                 </p>
                                    <p>
                                    <i>
                                        Voucher jest ważny 6 miesięcy od daty zakupu, nie ma wartości pieniężnej,
                                        nie podlega wymianie na gotówkę ani zwrotowi.
                                    </i>
                                </p>";
            }

            //get all attachments for email from db and parse into array
            $attachments = [];
            $sql = 'SELECT DISTINCT p.id_pdfAttachment,p.path,p.file_name FROM ' . _DB_PREFIX_ . 'pdfAttachment_files p
                    WHERE p.id_pdfAttachment = ' . $id_pdfAttachment;
            $filesToAttach = Db::getInstance()->executeS($sql);
            foreach ($filesToAttach as $file) {
                $newFile = [];
                $newFile['content'] = file_get_contents(_PS_ROOT_DIR_ . $file['path']); //File path
                $newFile['name'] = $file['file_name'];
                $newFile['mime'] = 'application/pdf';
                $attachments[] = $newFile;
            }


            Mail::Send((int)(Configuration::get('PS_LANG_DEFAULT')),
                'newsletter', // email template file to be use
                $mailTitle, // email subject
                array(
                    '{email}' => Configuration::get('PS_SHOP_EMAIL'), // sender email address
                    '{message}' => $mailContent, // email content
                    '{firstname}' => $firstname,
                    '{lastname}' => $lastname
                ),
                $customerMail, // receiver email address
                null, //Receiver name
                Configuration::get('PS_SHOP_EMAIL'), //Sender email
                Configuration::get("PS_SHOP_NAME"), // Sender name
                $attachments, //Attachments
                null, //SMTP mode
                _PS_MAIL_DIR_, //Mails directory
                true //Die after error?
            );
        }
    }


}
