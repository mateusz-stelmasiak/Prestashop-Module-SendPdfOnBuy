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
*  @author    PrestaShop SA <contact@prestashop.com>
*  @copyright 2007-2022 PrestaShop SA
*  @license   http://opensource.org/licenses/afl-3.0.php  Academic Free License (AFL 3.0)
*  International Registered Trademark & Property of PrestaShop SA
*/
$sql = array();

$sql[] = 'CREATE TABLE IF NOT EXISTS `' . _DB_PREFIX_ . 'pdfAttachments` (
    `id_pdfAttachment` int(11) NOT NULL AUTO_INCREMENT,
    `mail_title` varchar(1000) NOT NULL,
    `mail_content` LONGTEXT  NOT NULL,
        PRIMARY KEY  (`id_pdfAttachment`)
) ENGINE=' . _MYSQL_ENGINE_ . ' DEFAULT CHARSET=utf8;';

$sql[] = 'CREATE TABLE IF NOT EXISTS `' . _DB_PREFIX_ . 'pdfAttachment_files` (
    `id_file` int(11) NOT NULL AUTO_INCREMENT,
    `id_pdfAttachment`  int(11)  NOT NULL,
    `path` varchar(1000) NOT NULL,
    `file_name` varchar(1000) NOT NULL,
        PRIMARY KEY  (`id_file`),
        FOREIGN KEY (`id_pdfAttachment`) REFERENCES ' . _DB_PREFIX_ . 'pdfAttachments(`id_pdfAttachment`) ON DELETE CASCADE
) ENGINE=' . _MYSQL_ENGINE_ . ' DEFAULT CHARSET=utf8;';


$sql[] = 'CREATE TABLE IF NOT EXISTS `' . _DB_PREFIX_ . 'pdfAttachment_product` (
    `id_pdfAttachment_product` int(11) NOT NULL AUTO_INCREMENT,
    `id_pdfAttachment`  int(11)  NOT NULL,
    `id_product` int(10) NOT NULL,
        PRIMARY KEY  (`id_pdfAttachment_product`),
        FOREIGN KEY (`id_pdfAttachment`) REFERENCES ' . _DB_PREFIX_ . 'pdfAttachments(`id_pdfAttachment`) ON DELETE CASCADE
) ENGINE=' . _MYSQL_ENGINE_ . ' DEFAULT CHARSET=utf8;';



foreach ($sql as $query) {
    if (Db::getInstance()->execute($query) == false) {
        return false;
    }
}
